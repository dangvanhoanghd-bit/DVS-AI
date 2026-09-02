from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Iterable


@dataclass(frozen=True)
class OrderFlowSnapshot:
    symbol: str
    window_seconds: int
    buy_notional: float
    sell_notional: float
    delta_usd: float
    cumulative_cvd_usd: float
    cvd_slope_usd_per_sec: float
    long_liquidation_usd: float
    short_liquidation_usd: float
    liquidation_events: tuple[dict[str, Any], ...]
    trade_events: int
    liquidation_event_count: int
    newest_event_ts: float
    data_quality: str


class PersistentOrderFlowStore:
    """Thread-safe persistent order-flow accumulator.

    The store deliberately does not open network connections. A future
    WebSocket collector may feed Binance ``aggTrade`` and ``forceOrder``
    payloads through the ingestion methods. REST hydration can use the same
    path as a truthful bootstrap while ``realtime=False`` remains explicit.
    """

    def __init__(
        self,
        db_path: str | Path = "data/order_flow.sqlite3",
        retention_seconds: int = 6 * 3600,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_seconds = max(300, int(retention_seconds))
        self._lock = RLock()
        self._init_db()

    @staticmethod
    def _finite(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if math.isfinite(number) else default

    @staticmethod
    def _symbol(value: Any) -> str:
        return str(value or "").replace("/USDT:USDT", "USDT").upper()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS order_flow_events (
                    event_key TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_ts REAL NOT NULL,
                    side TEXT NOT NULL,
                    notional REAL NOT NULL,
                    signed_delta REAL NOT NULL,
                    realtime INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_order_flow_symbol_ts
                ON order_flow_events(symbol, event_ts);
                """
            )

    def ingest_agg_trades(
        self,
        symbol: str,
        trades: Iterable[dict[str, Any]],
        *,
        realtime: bool = False,
    ) -> int:
        raw_symbol = self._symbol(symbol)
        rows: list[tuple[Any, ...]] = []
        for trade in trades or ():
            trade_id = trade.get("a", trade.get("id"))
            ts_ms = self._finite(trade.get("T", trade.get("time")))
            price = self._finite(trade.get("p", trade.get("price")))
            quantity = self._finite(trade.get("q", trade.get("qty")))
            if not raw_symbol or trade_id is None or ts_ms <= 0 or price <= 0 or quantity <= 0:
                continue
            # Binance m=true means buyer is maker, so the aggressive side is SELL.
            aggressive_side = "SELL" if bool(trade.get("m", trade.get("isBuyerMaker", False))) else "BUY"
            notional = price * quantity
            signed = notional if aggressive_side == "BUY" else -notional
            rows.append((
                f"TRADE:{raw_symbol}:{trade_id}", raw_symbol, "TRADE",
                ts_ms / 1000.0, aggressive_side, notional, signed,
                1 if realtime else 0,
            ))
        return self._insert_rows(rows)

    def ingest_force_orders(
        self,
        events: Iterable[dict[str, Any]],
        *,
        realtime: bool = True,
    ) -> int:
        rows: list[tuple[Any, ...]] = []
        for envelope in events or ():
            order = envelope.get("o", envelope)
            raw_symbol = self._symbol(order.get("s", order.get("symbol")))
            ts_ms = self._finite(envelope.get("E", order.get("T", order.get("time"))))
            side = str(order.get("S", order.get("side", ""))).upper()
            price = self._finite(order.get("ap", order.get("p", order.get("price"))))
            quantity = self._finite(order.get("z", order.get("q", order.get("qty"))))
            if not raw_symbol or ts_ms <= 0 or side not in {"BUY", "SELL"} or price <= 0 or quantity <= 0:
                continue
            event_id = order.get("i") or order.get("orderId") or f"{int(ts_ms)}:{side}:{price}:{quantity}"
            notional = price * quantity
            rows.append((
                f"LIQ:{raw_symbol}:{event_id}", raw_symbol, "LIQUIDATION",
                ts_ms / 1000.0, side, notional, 0.0,
                1 if realtime else 0,
            ))
        return self._insert_rows(rows)

    def _insert_rows(self, rows: list[tuple[Any, ...]]) -> int:
        if not rows:
            return 0
        cutoff = time.time() - self.retention_seconds
        with self._lock, self._connect() as db:
            before = db.total_changes
            db.executemany(
                """INSERT OR IGNORE INTO order_flow_events
                (event_key, symbol, event_type, event_ts, side, notional,
                 signed_delta, realtime) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            inserted = db.total_changes - before
            db.execute("DELETE FROM order_flow_events WHERE event_ts < ?", (cutoff,))
        return int(inserted)


    def latest_trade_id(self, symbol: str) -> int | None:
        """Return the greatest persisted aggregate-trade ID for a symbol."""
        raw_symbol = self._symbol(symbol)
        prefix = f"TRADE:{raw_symbol}:"
        with self._lock, self._connect() as db:
            rows = db.execute(
                """SELECT event_key FROM order_flow_events
                   WHERE symbol = ? AND event_type = 'TRADE'
                   ORDER BY event_ts DESC LIMIT 200""",
                (raw_symbol,),
            ).fetchall()
        best: int | None = None
        for (event_key,) in rows:
            try:
                value = int(str(event_key).removeprefix(prefix))
            except (TypeError, ValueError):
                continue
            best = value if best is None else max(best, value)
        return best

    def snapshot(
        self,
        symbol: str,
        *,
        window_seconds: int = 300,
        now_ts: float | None = None,
    ) -> OrderFlowSnapshot:
        raw_symbol = self._symbol(symbol)
        now = float(now_ts if now_ts is not None else time.time())
        window = max(30, int(window_seconds))
        cutoff = now - window
        with self._lock, self._connect() as db:
            rows = db.execute(
                """SELECT event_type, event_ts, side, notional,
                          signed_delta, realtime
                   FROM order_flow_events
                   WHERE symbol = ? AND event_ts >= ? AND event_ts <= ?
                   ORDER BY event_ts ASC""",
                (raw_symbol, cutoff, now + 1.0),
            ).fetchall()
            cumulative_row = db.execute(
                """SELECT COALESCE(SUM(signed_delta), 0.0)
                   FROM order_flow_events
                   WHERE symbol = ? AND event_type = 'TRADE' AND event_ts <= ?""",
                (raw_symbol, now + 1.0),
            ).fetchone()
        buy = sell = long_liq = short_liq = 0.0
        trade_points: list[tuple[float, float]] = []
        liquidations: list[dict[str, Any]] = []
        running = 0.0
        realtime_seen = False
        newest = 0.0
        trade_count = 0
        liq_count = 0
        for event_type, event_ts, side, notional, signed_delta, realtime in rows:
            newest = max(newest, float(event_ts))
            realtime_seen = realtime_seen or bool(realtime)
            if event_type == "TRADE":
                trade_count += 1
                if side == "BUY": buy += float(notional)
                else: sell += float(notional)
                running += float(signed_delta)
                trade_points.append((float(event_ts), running))
            else:
                liq_count += 1
                if side == "SELL": long_liq += float(notional)
                else: short_liq += float(notional)
                liquidations.append({"side": side, "notional": float(notional), "timestamp": float(event_ts)})
        slope = 0.0
        if len(trade_points) >= 2:
            elapsed = trade_points[-1][0] - trade_points[0][0]
            if elapsed > 0:
                slope = (trade_points[-1][1] - trade_points[0][1]) / elapsed
        if realtime_seen and rows:
            quality = "REALTIME"
        elif rows:
            quality = "BOOTSTRAP"
        else:
            quality = "EMPTY"
        return OrderFlowSnapshot(
            symbol=raw_symbol,
            window_seconds=window,
            buy_notional=buy,
            sell_notional=sell,
            delta_usd=buy - sell,
            cumulative_cvd_usd=float(cumulative_row[0] if cumulative_row else 0.0),
            cvd_slope_usd_per_sec=slope,
            long_liquidation_usd=long_liq,
            short_liquidation_usd=short_liq,
            liquidation_events=tuple(liquidations),
            trade_events=trade_count,
            liquidation_event_count=liq_count,
            newest_event_ts=newest,
            data_quality=quality,
        )

    def diagnostics(self) -> dict[str, Any]:
        with self._lock, self._connect() as db:
            total, realtime = db.execute(
                """SELECT COUNT(*), COALESCE(SUM(realtime), 0)
                   FROM order_flow_events"""
            ).fetchone()
            symbols = db.execute(
                "SELECT COUNT(DISTINCT symbol) FROM order_flow_events"
            ).fetchone()[0]
        return {
            "db_path": str(self.db_path),
            "events": int(total),
            "realtime_events": int(realtime),
            "symbols": int(symbols),
            "retention_seconds": self.retention_seconds,
        }
