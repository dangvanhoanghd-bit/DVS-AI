from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class TrackedPositionStatus(str, Enum):
    OPEN = "OPEN"
    PROTECTED = "PROTECTED"
    TP1_HIT = "TP1_HIT"
    TP2_HIT = "TP2_HIT"
    STOPPED = "STOPPED"
    CLOSED = "CLOSED"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"


@dataclass(frozen=True)
class TrackedPosition:
    id: int
    symbol: str
    direction: str
    quantity: float
    entry_price: float
    mark_price: float
    invalidation: float
    tp1: float
    tp2: float
    status: TrackedPositionStatus
    unrealized_pnl: float
    realized_pnl: float
    client_order_id: str
    protective_stop_attached: bool
    opened_at: str
    updated_at: str


class PositionTracker:
    """SQLite-backed PAPER/TESTNET/LIVE-neutral position state."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS tracked_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    mark_price REAL NOT NULL,
                    invalidation REAL NOT NULL,
                    tp1 REAL NOT NULL,
                    tp2 REAL NOT NULL,
                    status TEXT NOT NULL,
                    unrealized_pnl REAL NOT NULL DEFAULT 0,
                    realized_pnl REAL NOT NULL DEFAULT 0,
                    client_order_id TEXT NOT NULL UNIQUE,
                    protective_stop_attached INTEGER NOT NULL DEFAULT 0,
                    opened_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_tracked_position_status
                ON tracked_positions(status, symbol)
            """)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def register_fill(
        self,
        *,
        symbol: str,
        direction: str,
        quantity: float,
        entry_price: float,
        invalidation: float,
        tp1: float,
        tp2: float,
        client_order_id: str,
        protective_stop_attached: bool = False,
    ) -> int:
        now = self._now()
        status = (
            TrackedPositionStatus.PROTECTED.value
            if protective_stop_attached
            else TrackedPositionStatus.OPEN.value
        )
        with self._connect() as con:
            cursor = con.execute("""
                INSERT OR IGNORE INTO tracked_positions (
                    symbol, direction, quantity, entry_price, mark_price,
                    invalidation, tp1, tp2, status, unrealized_pnl,
                    realized_pnl, client_order_id,
                    protective_stop_attached, opened_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?)
            """, (
                symbol,
                direction,
                float(quantity),
                float(entry_price),
                float(entry_price),
                float(invalidation),
                float(tp1),
                float(tp2),
                status,
                client_order_id,
                1 if protective_stop_attached else 0,
                now,
                now,
            ))
            if cursor.rowcount:
                return int(cursor.lastrowid)
            row = con.execute(
                "SELECT id FROM tracked_positions WHERE client_order_id=?",
                (client_order_id,),
            ).fetchone()
            return int(row[0])

    def set_protected(
        self,
        client_order_id: str,
        attached: bool = True,
    ) -> None:
        with self._connect() as con:
            con.execute("""
                UPDATE tracked_positions
                SET protective_stop_attached=?,
                    status=?,
                    updated_at=?
                WHERE client_order_id=?
                  AND status IN ('OPEN','PROTECTED')
            """, (
                1 if attached else 0,
                (
                    TrackedPositionStatus.PROTECTED.value
                    if attached
                    else TrackedPositionStatus.OPEN.value
                ),
                self._now(),
                client_order_id,
            ))

    def update_mark(
        self,
        client_order_id: str,
        mark_price: float,
    ) -> TrackedPosition | None:
        position = self.get(client_order_id)
        if position is None:
            return None
        side = 1.0 if position.direction == "LONG" else -1.0
        unrealized = (
            float(mark_price)-position.entry_price
        )*position.quantity*side
        status = position.status

        if position.direction == "LONG":
            if mark_price <= position.invalidation:
                status = TrackedPositionStatus.STOPPED
            elif mark_price >= position.tp2:
                status = TrackedPositionStatus.TP2_HIT
            elif mark_price >= position.tp1:
                status = TrackedPositionStatus.TP1_HIT
        else:
            if mark_price >= position.invalidation:
                status = TrackedPositionStatus.STOPPED
            elif mark_price <= position.tp2:
                status = TrackedPositionStatus.TP2_HIT
            elif mark_price <= position.tp1:
                status = TrackedPositionStatus.TP1_HIT

        realized = position.realized_pnl
        if status in (
            TrackedPositionStatus.STOPPED,
            TrackedPositionStatus.TP2_HIT,
        ):
            realized = unrealized
            unrealized = 0.0

        with self._connect() as con:
            con.execute("""
                UPDATE tracked_positions
                SET mark_price=?, unrealized_pnl=?, realized_pnl=?,
                    status=?, updated_at=?
                WHERE client_order_id=?
            """, (
                float(mark_price),
                float(unrealized),
                float(realized),
                status.value,
                self._now(),
                client_order_id,
            ))
        return self.get(client_order_id)

    def mark_reconciliation_failed(
        self,
        client_order_id: str,
    ) -> None:
        with self._connect() as con:
            con.execute("""
                UPDATE tracked_positions
                SET status=?, updated_at=?
                WHERE client_order_id=?
            """, (
                TrackedPositionStatus.RECONCILIATION_FAILED.value,
                self._now(),
                client_order_id,
            ))

    def get(self, client_order_id: str) -> TrackedPosition | None:
        with self._connect() as con:
            row = con.execute("""
                SELECT id, symbol, direction, quantity, entry_price,
                       mark_price, invalidation, tp1, tp2, status,
                       unrealized_pnl, realized_pnl, client_order_id,
                       protective_stop_attached, opened_at, updated_at
                FROM tracked_positions
                WHERE client_order_id=?
            """, (client_order_id,)).fetchone()
        if row is None:
            return None
        return TrackedPosition(
            id=int(row[0]),
            symbol=str(row[1]),
            direction=str(row[2]),
            quantity=float(row[3]),
            entry_price=float(row[4]),
            mark_price=float(row[5]),
            invalidation=float(row[6]),
            tp1=float(row[7]),
            tp2=float(row[8]),
            status=TrackedPositionStatus(str(row[9])),
            unrealized_pnl=float(row[10]),
            realized_pnl=float(row[11]),
            client_order_id=str(row[12]),
            protective_stop_attached=bool(row[13]),
            opened_at=str(row[14]),
            updated_at=str(row[15]),
        )

    def open_positions(self) -> list[TrackedPosition]:
        with self._connect() as con:
            ids = [
                row[0]
                for row in con.execute("""
                    SELECT client_order_id
                    FROM tracked_positions
                    WHERE status IN ('OPEN','PROTECTED','TP1_HIT')
                    ORDER BY id DESC
                """).fetchall()
            ]
        return [
            position
            for client_id in ids
            if (position := self.get(client_id)) is not None
        ]
