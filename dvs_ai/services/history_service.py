from __future__ import annotations
import sqlite3
from pathlib import Path

class HistoryService:
    def __init__(self, db_path: str = "data/dvs_signals.db") -> None:
        self.db_path = Path(db_path)

    def latest(self, limit: int = 300) -> list[tuple]:
        if not self.db_path.exists():
            return []
        with sqlite3.connect(self.db_path) as con:
            return con.execute("""
                SELECT generated_at, symbol, direction, entry_status,
                       confidence, long_trend, long_entry,
                       short_trend, short_entry, price, phase, oi_state,
                       COALESCE(outcome,'PENDING'),
                       COALESCE(r_multiple,0),
                       COALESCE(outcome_detail,'')
                FROM scan_signals
                ORDER BY id DESC LIMIT ?
            """, (int(limit),)).fetchall()


    def stats(self) -> dict[str, float]:
        if not self.db_path.exists():
            return {
                "count": 0,
                "ready": 0,
                "avg_confidence": 0.0,
                "resolved": 0,
                "wins": 0,
                "losses": 0,
                "ambiguous": 0,
                "expired": 0,
                "win_rate": 0.0,
                "avg_r": 0.0,
            }

        with sqlite3.connect(self.db_path) as con:
            row = con.execute("""
                SELECT
                    COUNT(*),
                    SUM(
                        CASE WHEN entry_status='READY'
                        THEN 1 ELSE 0 END
                    ),
                    COALESCE(AVG(confidence),0),
                    SUM(
                        CASE
                            WHEN outcome IN (
                                'TP2','INVALID','PARTIAL_STOP'
                            )
                            THEN 1 ELSE 0
                        END
                    ),
                    SUM(
                        CASE
                            WHEN outcome IN (
                                'TP2','INVALID','PARTIAL_STOP'
                            )
                             AND COALESCE(r_multiple,0)>0
                            THEN 1 ELSE 0
                        END
                    ),
                    SUM(
                        CASE
                            WHEN outcome IN (
                                'TP2','INVALID','PARTIAL_STOP'
                            )
                             AND COALESCE(r_multiple,0)<=0
                            THEN 1 ELSE 0
                        END
                    ),
                    SUM(
                        CASE
                            WHEN outcome IN (
                                'AMBIGUOUS',
                                'PARTIAL_AMBIGUOUS'
                            )
                            THEN 1 ELSE 0
                        END
                    ),
                    SUM(
                        CASE WHEN outcome='EXPIRED'
                        THEN 1 ELSE 0 END
                    ),
                    COALESCE(
                        AVG(
                            CASE
                                WHEN outcome IN (
                                    'TP2',
                                    'INVALID',
                                    'PARTIAL_STOP'
                                )
                                THEN r_multiple
                            END
                        ),
                        0
                    )
                FROM scan_signals
            """).fetchone()

        resolved = int(row[3] or 0)
        wins = int(row[4] or 0)
        return {
            "count": int(row[0] or 0),
            "ready": int(row[1] or 0),
            "avg_confidence": float(row[2] or 0.0),
            "resolved": resolved,
            "wins": wins,
            "losses": int(row[5] or 0),
            "ambiguous": int(row[6] or 0),
            "expired": int(row[7] or 0),
            "win_rate": (
                wins/resolved*100.0 if resolved else 0.0
            ),
            "avg_r": float(row[8] or 0.0),
        }

