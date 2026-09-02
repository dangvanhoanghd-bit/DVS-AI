from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import ExecutionIntent, ExecutionResult


class ExecutionAudit:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS execution_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    status TEXT NOT NULL,
                    client_order_id TEXT,
                    exchange_order_id TEXT,
                    average_price REAL,
                    fee_paid REAL,
                    message TEXT,
                    payload TEXT
                )
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_execution_audit_time
                ON execution_audit(timestamp)
            """)

    def record(
        self,
        intent: ExecutionIntent,
        result: ExecutionResult,
    ) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        payload = json.dumps(dict(result.raw), ensure_ascii=False)
        with self._connect() as con:
            con.execute("""
                INSERT INTO execution_audit (
                    timestamp, symbol, mode, side, order_type,
                    quantity, status, client_order_id,
                    exchange_order_id, average_price, fee_paid,
                    message, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now,
                intent.symbol,
                result.mode.value,
                intent.side.value,
                intent.order_type.value,
                intent.quantity,
                result.status.value,
                result.client_order_id,
                result.exchange_order_id,
                result.average_price,
                result.fee_paid,
                result.message,
                payload,
            ))
