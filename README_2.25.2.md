# DVS AI Alpha 2.25.2 — Resilient WebSocket Collector Audit

Run the release gate:

```bash
python -m pip install -r requirements.txt
python release_gate_2_25_2.py
```

The collector is evidence-only. It writes decoded public Binance Futures
`aggTrade` and `forceOrder` events to the persistent order-flow store. It does
not load credentials or send orders.
