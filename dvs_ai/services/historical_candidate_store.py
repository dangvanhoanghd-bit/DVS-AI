from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CandidatePerformanceSnapshot:
    snapshot_id: int
    candidate_id: str
    captured_at: str
    observations: int
    expectancy: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    brier: float
    ece: float
    reliability: float
    drift_state: str
    coverage: float
    regime_metrics: dict[str, Any]


class HistoricalCandidateStore:
    """Append-only candidate performance snapshots for evidence history."""

    def __init__(self, db_path: str = "data/dvs_paper_trades.db") -> None:
        self.db_path=Path(db_path); self.db_path.parent.mkdir(parents=True,exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS candidate_performance_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    observations INTEGER NOT NULL,
                    expectancy REAL NOT NULL,
                    max_drawdown REAL NOT NULL,
                    win_rate REAL NOT NULL,
                    profit_factor REAL NOT NULL,
                    brier REAL NOT NULL,
                    ece REAL NOT NULL,
                    reliability REAL NOT NULL,
                    drift_state TEXT NOT NULL,
                    coverage REAL NOT NULL,
                    regime_json TEXT NOT NULL,
                    snapshot_key TEXT
                )
            """)
            columns={row[1] for row in conn.execute("PRAGMA table_info(candidate_performance_snapshots)").fetchall()}
            if "snapshot_key" not in columns:
                conn.execute("ALTER TABLE candidate_performance_snapshots ADD COLUMN snapshot_key TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candidate_performance ON candidate_performance_snapshots(candidate_id,id)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_snapshot_key ON candidate_performance_snapshots(snapshot_key) WHERE snapshot_key IS NOT NULL")

    def _connect(self): return sqlite3.connect(str(self.db_path))

    @staticmethod
    def _finite(value: Any, default: float=0.0) -> float:
        try:
            number=float(value)
            return number if math.isfinite(number) else default
        except (TypeError,ValueError): return default

    def append(self, candidate_id: str, *, observations: int, expectancy: float,
               max_drawdown: float, win_rate: float, profit_factor: float,
               brier: float, ece: float, reliability: float, drift_state: str,
               coverage: float, regime_metrics: dict | None = None,
               captured_at: str | None = None, snapshot_key: str | None = None) -> int:
        cid=str(candidate_id).strip()
        if not cid: raise ValueError("candidate_id is required")
        stamp=captured_at or datetime.now(timezone.utc).isoformat()
        values=(cid,stamp,max(0,int(observations)),self._finite(expectancy),self._finite(max_drawdown),
                min(1.0,max(0.0,self._finite(win_rate))),max(0.0,self._finite(profit_factor)),
                min(1.0,max(0.0,self._finite(brier))),min(1.0,max(0.0,self._finite(ece))),
                min(1.0,max(0.0,self._finite(reliability))),str(drift_state).upper(),
                min(1.0,max(0.0,self._finite(coverage))),json.dumps(dict(regime_metrics or {}),ensure_ascii=False,sort_keys=True),
                str(snapshot_key).strip() if snapshot_key else None)
        with self._connect() as conn:
            cur=conn.execute("""
                INSERT INTO candidate_performance_snapshots
                (candidate_id,captured_at,observations,expectancy,max_drawdown,win_rate,profit_factor,brier,ece,reliability,drift_state,coverage,regime_json,snapshot_key)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,values)
            return int(cur.lastrowid)


    def append_once(self, candidate_id: str, *, snapshot_key: str, **kwargs) -> int | None:
        key=str(snapshot_key).strip()
        if not key:
            raise ValueError("snapshot_key is required")
        with self._connect() as conn:
            row=conn.execute("SELECT id FROM candidate_performance_snapshots WHERE snapshot_key=?",(key,)).fetchone()
        if row:
            return None
        try:
            return self.append(candidate_id, snapshot_key=key, **kwargs)
        except sqlite3.IntegrityError:
            return None

    def snapshots(self, candidate_id: str, *, limit: int=500) -> list[CandidatePerformanceSnapshot]:
        with self._connect() as conn:
            rows=conn.execute("""
                SELECT id,candidate_id,captured_at,observations,expectancy,max_drawdown,win_rate,profit_factor,brier,ece,reliability,drift_state,coverage,regime_json
                FROM candidate_performance_snapshots WHERE candidate_id=? ORDER BY id LIMIT ?
            """,(str(candidate_id),max(1,int(limit)))).fetchall()
        out=[]
        for row in rows:
            try: regime=json.loads(row[13]) if row[13] else {}
            except Exception: regime={}
            out.append(CandidatePerformanceSnapshot(int(row[0]),str(row[1]),str(row[2]),int(row[3]),float(row[4]),float(row[5]),float(row[6]),float(row[7]),float(row[8]),float(row[9]),float(row[10]),str(row[11]),float(row[12]),regime))
        return out

    def latest(self, candidate_id: str) -> CandidatePerformanceSnapshot | None:
        rows=self.snapshots(candidate_id,limit=100000)
        return rows[-1] if rows else None

    def comparison(self, candidate_ids: list[str]) -> list[dict[str, Any]]:
        result=[]
        for cid in candidate_ids:
            item=self.latest(cid)
            if item is None: continue
            result.append({
                "candidate_id":cid,"observations":item.observations,"expectancy":item.expectancy,
                "max_drawdown":item.max_drawdown,"win_rate":item.win_rate,"profit_factor":item.profit_factor,
                "brier":item.brier,"ece":item.ece,"reliability":item.reliability,
                "drift_state":item.drift_state,"coverage":item.coverage,"captured_at":item.captured_at,
            })
        return sorted(result,key=lambda x:(x["expectancy"],-x["max_drawdown"]),reverse=True)
