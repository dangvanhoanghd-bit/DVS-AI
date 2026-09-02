# DVS AI Alpha 2.25.3 — Gap Detection & Controlled Backfill Audit

Run the release gate:

```bash
python release_gate_2_25_3.py
```

This release backfills only bounded, contiguous Binance Futures `aggTrade` ID gaps. It never fabricates missing liquidation events and does not enable live execution.
