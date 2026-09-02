from __future__ import annotations

import logging
import threading
from typing import Any, Iterable

from dvs_ai.services.order_flow_gap_backfill import ControlledAggTradeBackfiller
from dvs_ai.services.order_flow_store import PersistentOrderFlowStore
from dvs_ai.services.order_flow_websocket_collector import ResilientOrderFlowCollector

log = logging.getLogger(__name__)


class OrderFlowRuntime:
    """Owns order-flow evidence lifecycle for the desktop application.

    This runtime is deliberately one-way: public market data -> evidence store.
    It has no dependency on execution, credentials, orders, or position sizing.
    """

    def __init__(
        self,
        provider,
        symbols: Iterable[str],
        *,
        store: PersistentOrderFlowStore | None = None,
        collector_factory=ResilientOrderFlowCollector,
        enabled: bool = True,
    ) -> None:
        self.provider = provider
        self.store = store or PersistentOrderFlowStore()
        self.enabled = bool(enabled)
        self._lock = threading.RLock()
        self._closed = False
        self._start_attempted = False
        self._start_error = ""
        self.backfiller = ControlledAggTradeBackfiller(
            self.store,
            self._fetch_agg_trades,
        )
        normalized_symbols = tuple(symbols or ()) or ("BTC/USDT:USDT",)
        self.collector = collector_factory(
            self.store,
            normalized_symbols,
            gap_backfiller=self.backfiller,
        )

    def _fetch_agg_trades(self, symbol: str, from_id: int, limit: int):
        return self.provider.fetch_agg_trades(
            symbol,
            limit=limit,
            from_id=from_id,
        )

    def start(self) -> bool:
        with self._lock:
            if self._closed or not self.enabled:
                return False
            self._start_attempted = True
        try:
            started = bool(self.collector.start())
            with self._lock:
                self._start_error = ""
            return started
        except Exception as exc:
            with self._lock:
                self._start_error = f"{type(exc).__name__}: {exc}"[:300]
            log.warning("Order-flow runtime failed to start: %s", exc)
            return False

    def stop(self, timeout: float = 5.0) -> None:
        try:
            self.collector.stop(timeout=timeout)
        except Exception as exc:
            log.warning("Order-flow runtime stop failed: %s", exc)

    def update_symbols(self, symbols: Iterable[str]) -> bool:
        """Synchronize a newly loaded market universe with the collector."""
        with self._lock:
            if self._closed or not self.enabled:
                return False
        try:
            changed = bool(self.collector.update_symbols(symbols))
            with self._lock:
                self._start_error = ""
            return changed
        except Exception as exc:
            with self._lock:
                self._start_error = f"{type(exc).__name__}: {exc}"[:300]
            log.warning("Order-flow symbol update failed: %s", exc)
            return False

    def close(self, timeout: float = 5.0) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self.stop(timeout=timeout)
        close_store = getattr(self.store, "close", None)
        if callable(close_store):
            try:
                close_store()
            except Exception as exc:
                log.warning("Order-flow store close failed: %s", exc)

    def diagnostics(self) -> dict[str, Any]:
        try:
            collector = dict(self.collector.diagnostics() or {})
        except Exception as exc:
            collector = {
                "state": "ERROR",
                "running": False,
                "last_error": f"{type(exc).__name__}: {exc}",
            }
        with self._lock:
            collector.update({
                "runtime_enabled": self.enabled,
                "runtime_closed": self._closed,
                "runtime_start_attempted": self._start_attempted,
                "runtime_start_error": self._start_error,
            })
        return collector
