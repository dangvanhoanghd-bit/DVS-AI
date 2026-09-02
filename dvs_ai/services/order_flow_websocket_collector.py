from __future__ import annotations

import json
import logging
import math
import random
import threading
import time
from dataclasses import dataclass, asdict
from typing import Any, Callable, Iterable, Protocol

from dvs_ai.services.order_flow_store import PersistentOrderFlowStore
from dvs_ai.services.order_flow_gap_backfill import ControlledAggTradeBackfiller

log = logging.getLogger(__name__)


class WebSocketConnection(Protocol):
    def recv(self) -> str | bytes | None: ...
    def close(self) -> None: ...


ConnectionFactory = Callable[[str, float], WebSocketConnection]


@dataclass(frozen=True)
class CollectorDiagnostics:
    state: str
    running: bool
    reconnects: int
    connections: int
    messages: int
    trades_ingested: int
    liquidations_ingested: int
    malformed_messages: int
    stale_disconnects: int
    last_message_age_seconds: float | None
    last_error: str
    symbols: tuple[str, ...]
    gaps_detected: int
    gaps_filled: int
    gaps_unresolved: int
    trades_backfilled: int
    liquidation_gap_warnings: int
    last_gap_status: str
    supervisor_restarts: int
    unexpected_worker_exits: int
    symbol_reconfigurations: int


class ResilientOrderFlowCollector:
    """Passive, fail-safe Binance order-flow WebSocket collector.

    The collector only writes evidence to ``PersistentOrderFlowStore``. It has
    no reference to execution, orders, credentials, GUI, or position sizing.
    A connection factory is injectable so lifecycle and failure behavior can
    be tested without a network.
    """

    BASE_URL = "wss://fstream.binance.com/stream?streams="

    def __init__(
        self,
        store: PersistentOrderFlowStore,
        symbols: Iterable[str],
        *,
        connection_factory: ConnectionFactory | None = None,
        stale_after_seconds: float = 20.0,
        connect_timeout_seconds: float = 10.0,
        reconnect_base_seconds: float = 1.0,
        reconnect_max_seconds: float = 30.0,
        jitter_ratio: float = 0.20,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        gap_backfiller: ControlledAggTradeBackfiller | None = None,
    ) -> None:
        self.store = store
        self.symbols = self._normalize_symbols(symbols)
        if not self.symbols:
            raise ValueError("at least one valid symbol is required")
        self.connection_factory = connection_factory or self._default_factory
        self.stale_after_seconds = max(2.0, float(stale_after_seconds))
        self.connect_timeout_seconds = max(1.0, float(connect_timeout_seconds))
        self.reconnect_base_seconds = max(0.05, float(reconnect_base_seconds))
        self.reconnect_max_seconds = max(
            self.reconnect_base_seconds, float(reconnect_max_seconds)
        )
        self.jitter_ratio = min(0.50, max(0.0, float(jitter_ratio)))
        self._clock = clock
        self._sleeper = sleeper
        self.gap_backfiller = gap_backfiller
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._connection: WebSocketConnection | None = None
        self._lock = threading.RLock()
        self._state = "STOPPED"
        self._connections = 0
        self._reconnects = 0
        self._messages = 0
        self._trades_ingested = 0
        self._liquidations_ingested = 0
        self._malformed_messages = 0
        self._stale_disconnects = 0
        self._last_message_at: float | None = None
        self._last_error = ""
        self._last_trade_id: dict[str, int] = {}
        self._gaps_detected = 0
        self._gaps_filled = 0
        self._gaps_unresolved = 0
        self._trades_backfilled = 0
        self._liquidation_gap_warnings = 0
        self._last_gap_status = ""
        self._supervisor_restarts = 0
        self._unexpected_worker_exits = 0
        self._symbol_reconfigurations = 0

    @staticmethod
    def _normalize_symbols(symbols: Iterable[str]) -> tuple[str, ...]:
        result: list[str] = []
        seen: set[str] = set()
        for value in symbols or ():
            symbol = str(value or "").upper().replace("/USDT:USDT", "USDT")
            if not symbol.endswith("USDT") or not symbol.replace("USDT", "").isalnum():
                continue
            if symbol not in seen:
                seen.add(symbol)
                result.append(symbol)
        return tuple(result)

    def stream_url(self) -> str:
        streams: list[str] = []
        with self._lock:
            symbols = self.symbols
        for symbol in symbols:
            lower = symbol.lower()
            streams.extend((f"{lower}@aggTrade", f"{lower}@forceOrder"))
        return self.BASE_URL + "/".join(streams)

    def update_symbols(self, symbols: Iterable[str]) -> bool:
        """Atomically replace subscriptions and reconnect only when changed.

        Closing the current passive market-data socket makes the existing
        receive loop reconnect using the new immutable symbol snapshot.  No
        order, execution, credential, or trading state is touched.
        """
        normalized = self._normalize_symbols(symbols)
        if not normalized:
            raise ValueError("at least one valid symbol is required")
        with self._lock:
            if normalized == self.symbols:
                return False
            self.symbols = normalized
            self._symbol_reconfigurations += 1
            connection = self._connection
            running = bool(self._thread and self._thread.is_alive())
            if running:
                self._state = "RECONFIGURING"
        if connection is not None:
            try:
                connection.close()
            except Exception as exc:
                self._set_state(
                    "RECONFIGURING", f"{type(exc).__name__}: {exc}"
                )
        return True

    @staticmethod
    def _default_factory(url: str, timeout: float) -> WebSocketConnection:
        try:
            import websocket  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise RuntimeError(
                "websocket-client is required for live order-flow collection"
            ) from exc
        return websocket.create_connection(
            url,
            timeout=timeout,
            enable_multithread=True,
        )

    def start(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._supervised_run,
                name="dvs-order-flow-ws",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        connection = None
        with self._lock:
            connection = self._connection
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(max(0.0, float(timeout)))
        with self._lock:
            self._state = "STOPPED"
            self._connection = None

    def _set_state(self, state: str, error: str = "") -> None:
        with self._lock:
            self._state = state
            if error:
                self._last_error = error[:300]

    def _bounded_backoff_delay(self, attempt: int) -> float:
        """Return a capped delay without ever constructing an unbounded int.

        ``min(max_delay, base * 2**attempt)`` is not safe because Python
        evaluates the exponential operand before ``min``.  A long offline run
        can therefore raise ``OverflowError`` and permanently kill the daemon
        thread.  Cap the exponent first, then perform bounded float math.
        """
        exponent = max(0, int(attempt) - 1)
        ratio = self.reconnect_max_seconds / self.reconnect_base_seconds
        if ratio <= 1.0:
            return self.reconnect_max_seconds
        max_exponent = max(0.0, math.log2(ratio))
        safe_exponent = min(exponent, max_exponent)
        return min(
            self.reconnect_max_seconds,
            self.reconnect_base_seconds * (2.0 ** safe_exponent),
        )

    def _supervised_run(self) -> None:
        """Keep the collector observable and recover from unexpected exits."""
        supervisor_attempt = 0
        while not self._stop.is_set():
            try:
                self._run()
            except Exception as exc:
                if self._stop.is_set():
                    break
                supervisor_attempt += 1
                with self._lock:
                    self._supervisor_restarts += 1
                    self._last_error = (
                        f"SUPERVISOR:{type(exc).__name__}: {exc}"
                    )[:300]
                self._set_state("SUPERVISOR_BACKOFF")
                log.exception("Order-flow worker exited unexpectedly; restarting")
                self._stop.wait(self._bounded_backoff_delay(supervisor_attempt))
            else:
                if self._stop.is_set():
                    break
                supervisor_attempt += 1
                with self._lock:
                    self._unexpected_worker_exits += 1
                    self._supervisor_restarts += 1
                    self._last_error = "SUPERVISOR: worker returned without stop"
                self._set_state("SUPERVISOR_BACKOFF")
                self._stop.wait(self._bounded_backoff_delay(supervisor_attempt))
        self._set_state("STOPPED")

    def _run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            self._set_state("CONNECTING")
            connection: WebSocketConnection | None = None
            try:
                connection = self.connection_factory(
                    self.stream_url(), self.connect_timeout_seconds
                )
                with self._lock:
                    self._connection = connection
                    self._connections += 1
                    if self._connections > 1:
                        # forceOrder has no truthful REST replay endpoint.
                        self._liquidation_gap_warnings += 1
                    self._last_error = ""
                self._set_state("CONNECTED")
                attempt = 0
                self._receive_loop(connection)
            except Exception as exc:
                if not self._stop.is_set():
                    self._set_state("BACKOFF", f"{type(exc).__name__}: {exc}")
                    attempt += 1
                    with self._lock:
                        self._reconnects += 1
            finally:
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        pass
                with self._lock:
                    if self._connection is connection:
                        self._connection = None
            if self._stop.is_set():
                break
            delay = self._bounded_backoff_delay(attempt)
            if self.jitter_ratio:
                delay *= 1.0 + random.uniform(-self.jitter_ratio, self.jitter_ratio)
            self._stop.wait(max(0.01, delay))
        self._set_state("STOPPED")

    def _receive_loop(self, connection: WebSocketConnection) -> None:
        last_activity = self._clock()
        while not self._stop.is_set():
            try:
                raw = connection.recv()
            except TimeoutError:
                raw = None
            now = self._clock()
            if raw is None:
                if now - last_activity >= self.stale_after_seconds:
                    with self._lock:
                        self._stale_disconnects += 1
                    raise TimeoutError("order-flow stream became stale")
                continue
            last_activity = now
            with self._lock:
                self._last_message_at = now
                self._messages += 1
            self.process_message(raw)

    def process_message(self, raw: str | bytes | dict[str, Any]) -> bool:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            envelope = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(envelope, dict):
                raise ValueError("message is not an object")
            payload = envelope.get("data", envelope)
            if not isinstance(payload, dict):
                raise ValueError("payload is not an object")
            event_type = str(payload.get("e", ""))
            if event_type == "aggTrade":
                symbol = str(payload.get("s") or "").upper()
                try:
                    trade_id = int(payload.get("a"))
                except (TypeError, ValueError):
                    raise ValueError("aggTrade missing numeric aggregate id")
                previous = self._last_trade_id.get(symbol)
                if previous is None:
                    previous = self.store.latest_trade_id(symbol)
                if previous is not None and trade_id > previous + 1:
                    self._handle_trade_gap(symbol, previous + 1, trade_id - 1)
                inserted = self.store.ingest_agg_trades(symbol, [payload], realtime=True)
                self._last_trade_id[symbol] = max(trade_id, previous or trade_id)
                with self._lock:
                    self._trades_ingested += inserted
                return inserted > 0
            if event_type == "forceOrder":
                inserted = self.store.ingest_force_orders([payload], realtime=True)
                with self._lock:
                    self._liquidations_ingested += inserted
                return inserted > 0
            raise ValueError(f"unsupported event type: {event_type or 'missing'}")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            with self._lock:
                self._malformed_messages += 1
            return False

    def _handle_trade_gap(self, symbol: str, from_id: int, to_id: int) -> None:
        with self._lock:
            self._gaps_detected += 1
        if self.gap_backfiller is None:
            with self._lock:
                self._gaps_unresolved += 1
                self._last_gap_status = f"UNRESOLVED:{symbol}:{from_id}-{to_id}:no backfiller"
            return
        result = self.gap_backfiller.backfill(symbol, from_id, to_id)
        with self._lock:
            self._last_gap_status = (
                f"{result.status}:{symbol}:{from_id}-{to_id}"
                + (f":{result.reason}" if result.reason else "")
            )[:300]
            if result.status == "FILLED":
                self._gaps_filled += 1
                self._trades_backfilled += result.inserted
            else:
                self._gaps_unresolved += 1

    def diagnostics(self) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            age = (
                None if self._last_message_at is None
                else max(0.0, now - self._last_message_at)
            )
            return asdict(CollectorDiagnostics(
                state=self._state,
                running=bool(self._thread and self._thread.is_alive()),
                reconnects=self._reconnects,
                connections=self._connections,
                messages=self._messages,
                trades_ingested=self._trades_ingested,
                liquidations_ingested=self._liquidations_ingested,
                malformed_messages=self._malformed_messages,
                stale_disconnects=self._stale_disconnects,
                last_message_age_seconds=age,
                last_error=self._last_error,
                symbols=self.symbols,
                gaps_detected=self._gaps_detected,
                gaps_filled=self._gaps_filled,
                gaps_unresolved=self._gaps_unresolved,
                trades_backfilled=self._trades_backfilled,
                liquidation_gap_warnings=self._liquidation_gap_warnings,
                last_gap_status=self._last_gap_status,
                supervisor_restarts=self._supervisor_restarts,
                unexpected_worker_exits=self._unexpected_worker_exits,
                symbol_reconfigurations=self._symbol_reconfigurations,
            ))
