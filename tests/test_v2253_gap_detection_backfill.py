import time

from dvs_ai.services.order_flow_gap_backfill import ControlledAggTradeBackfiller
from dvs_ai.services.order_flow_store import PersistentOrderFlowStore
from dvs_ai.services.order_flow_websocket_collector import ResilientOrderFlowCollector


def trade(trade_id: int, *, ts_ms: int | None = None):
    return {
        "e": "aggTrade", "s": "BTCUSDT", "a": trade_id,
        "T": ts_ms or int(time.time() * 1000), "p": "100", "q": "1", "m": False,
    }


def test_contiguous_gap_is_backfilled_without_double_counting(tmp_path):
    store = PersistentOrderFlowStore(tmp_path / "flow.sqlite3")
    calls = []
    def fetcher(symbol, from_id, limit):
        calls.append((symbol, from_id, limit))
        return [trade(i) for i in range(from_id, from_id + limit)]
    backfill = ControlledAggTradeBackfiller(store, fetcher, max_gap_trades=10)
    collector = ResilientOrderFlowCollector(store, ["BTCUSDT"], gap_backfiller=backfill)
    assert collector.process_message(trade(10)) is True
    assert collector.process_message(trade(13)) is True
    snap = store.snapshot("BTCUSDT", now_ts=time.time() + 1)
    assert snap.trade_events == 4
    assert snap.cumulative_cvd_usd == 400
    diag = collector.diagnostics()
    assert diag["gaps_detected"] == 1
    assert diag["gaps_filled"] == 1
    assert diag["trades_backfilled"] == 2
    assert calls == [("BTCUSDT", 11, 2)]
    # Replaying REST data remains harmless because event keys are stable.
    assert backfill.backfill("BTCUSDT", 11, 12).inserted == 0
    assert store.snapshot("BTCUSDT", now_ts=time.time() + 1).cumulative_cvd_usd == 400


def test_non_contiguous_or_oversized_gap_stays_unresolved(tmp_path):
    store = PersistentOrderFlowStore(tmp_path / "flow.sqlite3")
    broken = ControlledAggTradeBackfiller(
        store, lambda symbol, from_id, limit: [trade(from_id + 1)], max_gap_trades=3
    )
    result = broken.backfill("BTCUSDT", 20, 21)
    assert result.status == "UNRESOLVED"
    assert "non-contiguous" in result.reason
    result = broken.backfill("BTCUSDT", 1, 10)
    assert result.status == "UNRESOLVED"
    assert "exceeds" in result.reason
    assert store.snapshot("BTCUSDT", now_ts=time.time() + 1).trade_events == 0


def test_collector_without_backfiller_reports_gap_instead_of_hiding_it(tmp_path):
    store = PersistentOrderFlowStore(tmp_path / "flow.sqlite3")
    collector = ResilientOrderFlowCollector(store, ["BTCUSDT"])
    collector.process_message(trade(1))
    collector.process_message(trade(3))
    diag = collector.diagnostics()
    assert diag["gaps_detected"] == 1
    assert diag["gaps_unresolved"] == 1
    assert "no backfiller" in diag["last_gap_status"]


def test_liquidation_gap_is_warning_only_and_never_fabricated(tmp_path):
    store = PersistentOrderFlowStore(tmp_path / "flow.sqlite3")
    collector = ResilientOrderFlowCollector(store, ["BTCUSDT"])
    assert not hasattr(ControlledAggTradeBackfiller, "backfill_force_orders")
    assert store.snapshot("BTCUSDT", now_ts=time.time() + 1).liquidation_event_count == 0
