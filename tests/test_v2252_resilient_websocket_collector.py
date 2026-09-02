import json
import time
from pathlib import Path

from dvs_ai.services.order_flow_store import PersistentOrderFlowStore
from dvs_ai.services.order_flow_websocket_collector import ResilientOrderFlowCollector


def collector(tmp_path):
    store = PersistentOrderFlowStore(tmp_path / "flow.sqlite3")
    return store, ResilientOrderFlowCollector(
        store, ["BTC/USDT:USDT", "ethusdt", "bad"], jitter_ratio=0
    )


def test_subscription_is_deduplicated_and_read_only(tmp_path):
    _, item = collector(tmp_path)
    assert item.symbols == ("BTCUSDT", "ETHUSDT")
    url = item.stream_url()
    assert url.count("btcusdt@aggTrade") == 1
    assert "@forceOrder" in url
    assert not hasattr(item, "place_order")


def test_message_ingestion_and_dedup(tmp_path):
    store, item = collector(tmp_path)
    now_ms = int(time.time()*1000)
    trade = {"e":"aggTrade","s":"BTCUSDT","a":1,"T":now_ms,"p":"100","q":"2","m":False}
    assert item.process_message({"stream":"x", "data":trade}) is True
    assert item.process_message(json.dumps({"data":trade})) is False
    liq = {"e":"forceOrder","E":now_ms+100,"o":{"s":"BTCUSDT","S":"SELL","i":9,"ap":"100","z":"3"}}
    assert item.process_message(liq) is True
    snap = store.snapshot("BTCUSDT", now_ts=time.time()+1, window_seconds=300)
    assert snap.data_quality == "REALTIME"
    assert snap.buy_notional == 200
    assert snap.long_liquidation_usd == 300


def test_malformed_messages_fail_safe(tmp_path):
    _, item = collector(tmp_path)
    for value in ("{", b"\xff", {}, {"e":"unknown"}, []):
        assert item.process_message(value) is False
    assert item.diagnostics()["malformed_messages"] == 5


class FakeConnection:
    def __init__(self, messages): self.messages=list(messages); self.closed=False
    def recv(self):
        if self.messages: return self.messages.pop(0)
        raise RuntimeError("disconnect")
    def close(self): self.closed=True


def test_reconnect_lifecycle_and_idempotent_start_stop(tmp_path):
    store = PersistentOrderFlowStore(tmp_path / "flow.sqlite3")
    calls=[]
    def factory(url, timeout):
        calls.append(url)
        return FakeConnection([json.dumps({"data":{"e":"aggTrade","s":"BTCUSDT","a":len(calls),"T":int(time.time()*1000),"p":"1","q":"1","m":False}})])
    item = ResilientOrderFlowCollector(
        store,["BTCUSDT"],connection_factory=factory,
        reconnect_base_seconds=.01,reconnect_max_seconds=.01,jitter_ratio=0,
    )
    assert item.start() is True
    assert item.start() is False
    deadline=time.time()+1
    while len(calls)<2 and time.time()<deadline: time.sleep(.01)
    item.stop()
    diag=item.diagnostics()
    assert len(calls)>=2
    assert diag["reconnects"]>=1
    assert diag["state"]=="STOPPED"
