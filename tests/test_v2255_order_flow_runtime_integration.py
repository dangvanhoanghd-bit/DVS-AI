from __future__ import annotations

from pathlib import Path
from dvs_ai.services.order_flow_runtime import OrderFlowRuntime


class FakeProvider:
    def fetch_agg_trades(self, symbol, limit=500, *, from_id=None, **kwargs):
        return []


class FakeStore:
    def __init__(self):
        self.closed = 0
    def close(self):
        self.closed += 1


class FakeCollector:
    def __init__(self, store, symbols, gap_backfiller=None):
        self.store = store
        self.symbols = tuple(symbols)
        self.gap_backfiller = gap_backfiller
        self.starts = 0
        self.stops = 0
    def start(self):
        self.starts += 1
        return self.starts == 1
    def stop(self, timeout=5.0):
        self.stops += 1
    def diagnostics(self):
        return {"state": "CONNECTED", "running": True, "messages": 7}


def test_runtime_owns_shared_store_and_lifecycle_is_idempotent():
    store = FakeStore()
    runtime = OrderFlowRuntime(
        FakeProvider(), ["BTC/USDT:USDT", "BTC/USDT:USDT"],
        store=store, collector_factory=FakeCollector,
    )
    assert runtime.collector.store is store
    assert runtime.backfiller.store is store
    assert runtime.start() is True
    assert runtime.start() is False
    assert runtime.diagnostics()["state"] == "CONNECTED"
    runtime.close()
    runtime.close()
    assert runtime.collector.stops == 1
    assert store.closed == 1


def test_disabled_runtime_fails_closed_without_starting_collector():
    runtime = OrderFlowRuntime(
        FakeProvider(), ["ETH/USDT:USDT"],
        store=FakeStore(), collector_factory=FakeCollector, enabled=False,
    )
    assert runtime.start() is False
    assert runtime.collector.starts == 0
    diag = runtime.diagnostics()
    assert diag["runtime_enabled"] is False
    runtime.close()


def test_scanner_accepts_injected_microstructure_service():
    source = Path("dvs_ai/services/scanner.py").read_text(encoding="utf-8")
    assert "microstructure_service=None" in source
    assert "microstructure_service or MicrostructureService(provider)" in source


def test_runtime_has_no_execution_dependency():
    import inspect
    import dvs_ai.services.order_flow_runtime as module
    source = inspect.getsource(module)
    forbidden = ("TradeIntent", "PositionSizer", "send_order", "execution_live_enabled")
    assert all(token not in source for token in forbidden)
