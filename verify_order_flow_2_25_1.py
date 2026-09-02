from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from dvs_ai.services.order_flow_store import PersistentOrderFlowStore


def main() -> int:
    with tempfile.TemporaryDirectory() as folder:
        store = PersistentOrderFlowStore(Path(folder) / "flow.sqlite3")
        now = int(time.time() * 1000)
        trades = [
            {"a": 1, "T": now - 1000, "p": "100", "q": "2", "m": False},
            {"a": 2, "T": now, "p": "100", "q": "1", "m": True},
        ]
        assert store.ingest_agg_trades("BTCUSDT", trades) == 2
        assert store.ingest_agg_trades("BTCUSDT", trades) == 0
        assert store.ingest_force_orders([
            {"E": now, "o": {"i": 7, "s": "BTCUSDT", "S": "SELL", "ap": "100", "z": "3"}}
        ]) == 1
        snap = store.snapshot("BTCUSDT", now_ts=now / 1000 + 1)
        assert snap.delta_usd == 100.0
        assert snap.cumulative_cvd_usd == 100.0
        assert snap.long_liquidation_usd == 300.0
        assert snap.data_quality == "REALTIME"
    manifest = json.loads(Path("ORDER_FLOW_TRUTH_MANIFEST.json").read_text())
    assert manifest["version"] == "2.25.1"
    assert any(x["status"] == "NOT_IMPLEMENTED" for x in manifest["claims"])
    print("ORDER FLOW 2.25.1 VERIFIER: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
