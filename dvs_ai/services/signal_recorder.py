from __future__ import annotations
import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from dvs_ai.domain.models import CoinAnalysis

logger = logging.getLogger(__name__)


class SignalRecorder:
    def __init__(self, path: str = "data/dvs_signals.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.path)

    def _columns(self, con) -> set[str]:
        return {row[1] for row in con.execute("PRAGMA table_info(scan_signals)")}

    def _init_db(self):
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS scan_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    generated_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_status TEXT NOT NULL,
                    priority_status TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    long_trend REAL NOT NULL,
                    long_entry REAL NOT NULL,
                    short_trend REAL NOT NULL,
                    short_entry REAL NOT NULL,
                    price REAL NOT NULL,
                    phase TEXT NOT NULL,
                    oi_state TEXT NOT NULL,
                    entry_low REAL,
                    entry_high REAL,
                    invalidation REAL,
                    tp1 REAL,
                    tp2 REAL
                )
            """)
            cols = self._columns(con)
            migrations = {
                "scan_id": "TEXT",
                "outcome": "TEXT DEFAULT 'PENDING'",
                "outcome_time": "TEXT",
                "outcome_price": "REAL",
                "r_multiple": "REAL",
                "outcome_detail": "TEXT",
                "tp1_hit_time": "TEXT",
                "tp1_realized_r": "REAL DEFAULT 0",
            }
            for name, ddl in migrations.items():
                if name not in cols:
                    con.execute(f"ALTER TABLE scan_signals ADD COLUMN {name} {ddl}")
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_pending
                ON scan_signals(outcome, generated_at)
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_symbol_time
                ON scan_signals(symbol, generated_at)
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS error_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT,
                    direction TEXT,
                    error_type TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    stack_trace TEXT,
                    context TEXT,
                    source TEXT NOT NULL
                )
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_error_time
                ON error_logs(timestamp DESC)
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_error_source
                ON error_logs(source, timestamp DESC)
            """)


    def record_error(
        self,
        symbol: str | None = None,
        direction: str | None = None,
        error_type: str = "Exception",
        error_message: str = "",
        stack_trace: str | None = None,
        context: dict | None = None,
        source: str = "AUTO_PAPER_TRADE",
    ) -> bool:
        """
        Persist a structured runtime error for later audit.

        Returns True when the database write succeeds. Database logging failure
        never replaces the original application error; it falls back to Python
        logging and stderr.
        """
        timestamp = datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        safe_context = context or {}
        try:
            context_text = json.dumps(
                safe_context,
                ensure_ascii=False,
                default=str,
            )[:2000]
        except Exception:
            context_text = repr(safe_context)[:2000]

        message = str(error_message or error_type)[:1000]
        trace = (
            str(stack_trace)[:8000]
            if stack_trace
            else None
        )

        try:
            with self._connect() as con:
                con.execute("""
                    INSERT INTO error_logs (
                        timestamp,
                        symbol,
                        direction,
                        error_type,
                        error_message,
                        stack_trace,
                        context,
                        source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    timestamp,
                    symbol,
                    direction,
                    str(error_type or "Exception")[:200],
                    message,
                    trace,
                    context_text,
                    str(source or "UNKNOWN")[:200],
                ))
            return True
        except Exception as db_error:
            logger.exception(
                "Error audit write failed | symbol=%s direction=%s "
                "source=%s original=%s database=%s",
                symbol,
                direction,
                source,
                message,
                db_error,
            )
            print(
                f"[ERROR_LOG_FALLBACK] {symbol or '-'} "
                f"{direction or '-'} [{source}] {message}"
            )
            print(f"Database logging error: {db_error}")
            return False

    def latest_errors(
        self,
        limit: int = 200,
        source: str | None = None,
    ) -> list[tuple]:
        """Return recent structured runtime errors for UI/audit tools."""
        with self._connect() as con:
            return con.execute("""
                SELECT timestamp, symbol, direction, error_type,
                       error_message, source, context
                FROM error_logs
                WHERE (? IS NULL OR source=?)
                ORDER BY id DESC
                LIMIT ?
            """, (
                source,
                source,
                max(1, int(limit)),
            )).fetchall()

    def error_stats(self) -> dict[str, int]:
        """Compact persistent error counts."""
        with self._connect() as con:
            row = con.execute("""
                SELECT COUNT(*),
                       SUM(
                           CASE
                               WHEN timestamp >= datetime(
                                   'now','-24 hours'
                               )
                               THEN 1 ELSE 0
                           END
                       ),
                       COUNT(DISTINCT source)
                FROM error_logs
            """).fetchone()
        return {
            "total": int(row[0] or 0),
            "last_24h": int(row[1] or 0),
            "sources": int(row[2] or 0),
        }


    def record(self, a: CoinAnalysis, scan_id: str | None = None):
        # Giảm record WAIT trùng nhau: chỉ lưu nếu tín hiệu đủ đáng chú ý,
        # hoặc chưa có record gần nhất cùng symbol/status trong 10 phút.
        scan_id = scan_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        with self._connect() as con:
            latest = con.execute("""
                SELECT generated_at, entry_status, direction, confidence
                FROM scan_signals
                WHERE symbol=?
                ORDER BY id DESC LIMIT 1
            """, (a.symbol,)).fetchone()

            should_record = (
                a.entry_status.value in ("SETUP", "READY", "RUNNING")
                or a.confidence_score >= 45
            )
            if latest and not should_record:
                try:
                    old_time = datetime.strptime(latest[0], "%Y-%m-%d %H:%M:%S")
                    age = (datetime.now() - old_time).total_seconds()
                    same = (
                        latest[1] == a.entry_status.value
                        and latest[2] == a.direction
                        and abs(float(latest[3]) - a.confidence_score) < 5
                    )
                    if age < 600 and same:
                        return
                except Exception:
                    pass

            p = a.trade_plan
            con.execute("""
                INSERT INTO scan_signals (
                    generated_at,scan_id,symbol,direction,entry_status,priority_status,
                    confidence,long_trend,long_entry,short_trend,short_entry,
                    price,phase,oi_state,entry_low,entry_high,invalidation,tp1,tp2,
                    outcome
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                a.generated_at, scan_id, a.symbol, a.direction, a.entry_status.value,
                a.priority_status, a.confidence_score, a.long_trend_score,
                a.long_entry_score, a.short_trend_score, a.short_entry_score,
                a.snapshot.last_price, a.phase_summary, a.oi_state,
                p.entry_low, p.entry_high, p.invalidation, p.tp1, p.tp2, "PENDING"
            ))
