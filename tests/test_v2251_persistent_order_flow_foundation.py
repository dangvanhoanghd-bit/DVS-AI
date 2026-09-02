from __future__ import annotations

from pathlib import Path
import time

from dvs_ai.services.order_flow_store import PersistentOrderFlowStore


def trade(event_id, ts_ms, price, qty, buyer_maker=False):
    return {"a": event_id, "T": ts_ms, "p": str(price), "q": str(qty), "m": buyer_maker}


def force(order_id, ts_ms, side, price, qty):
    return {"E": ts_ms, "o": {"i": order_id, "s": "BTCUSDT", "S": side, "ap": str(price), "z": str(qty)}}


def test_agg_trade_dedup_and_cvd_persistence(tmp_path: Path):
    store = PersistentOrderFlowStore(tmp_path / "flow.sqlite3")
    now_ms = int(time.time() * 1000)
    events = [
        trade(1, now_ms - 1_000, 100, 2, False),  # aggressive BUY +200
        trade(2, now_ms, 100, 1, True),           # aggressive SELL -100
    ]
    assert store.ingest_agg_trades("BTC/USDT:USDT", events) == 2
    assert store.ingest_agg_trades("BTC/USDT:USDT", events) == 0
    snap = store.snapshot("BTC/USDT:USDT", now_ts=now_ms / 1000 + 1, window_seconds=300)
    assert snap.buy_notional == 200
    assert snap.sell_notional == 100
    assert snap.delta_usd == 100
    assert snap.cumulative_cvd_usd == 100
    assert snap.trade_events == 2
    assert snap.data_quality == "BOOTSTRAP"


def test_force_order_mapping_and_realtime_quality(tmp_path: Path):
    store = PersistentOrderFlowStore(tmp_path / "flow.sqlite3")
    now_ms = int(time.time() * 1000)
    events = [
        force(10, now_ms - 1_000, "SELL", 100, 3),  # long liquidation
        force(11, now_ms, "BUY", 100, 2),           # short liquidation
    ]
    assert store.ingest_force_orders(events) == 2
    assert store.ingest_force_orders(events) == 0
    snap = store.snapshot("BTCUSDT", now_ts=now_ms / 1000 + 1, window_seconds=300)
    assert snap.long_liquidation_usd == 300
    assert snap.short_liquidation_usd == 200
    assert snap.liquidation_event_count == 2
    assert snap.data_quality == "REALTIME"
    assert [x["side"] for x in snap.liquidation_events] == ["SELL", "BUY"]


def test_invalid_nan_and_incomplete_events_fail_closed(tmp_path: Path):
    store = PersistentOrderFlowStore(tmp_path / "flow.sqlite3")
    assert store.ingest_agg_trades("BTCUSDT", [{"a": 1, "T": 1, "p": "nan", "q": 2}]) == 0
    assert store.ingest_force_orders([{"E": 1, "o": {"s": "BTCUSDT", "S": "SELL"}}]) == 0
    snap = store.snapshot("BTCUSDT", now_ts=10, window_seconds=30)
    assert snap.data_quality == "EMPTY"
    assert snap.delta_usd == 0


def test_retention_cleanup(tmp_path: Path):
    store = PersistentOrderFlowStore(tmp_path / "flow.sqlite3", retention_seconds=300)
    # ancient event is inserted then removed by retention cleanup
    store.ingest_agg_trades("BTCUSDT", [trade(1, 1_000, 100, 1)])
    assert store.diagnostics()["events"] == 0
