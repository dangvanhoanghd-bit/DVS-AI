# DVS AI Alpha 3.5.0 — Qualification Batch Runner

- Adds a separate persistent-QThread Unified Core runtime for qualification batches.
- Submits every completed non-BTC scan result; no user click is required.
- Records paired Legacy/Unified observations through the existing idempotent SQLite store.
- Uses a bounded FIFO batch queue and fail-closed rejection when saturated.
- Keeps interactive shadow comparison and batch qualification on separate isolated runtimes.
- Paper authority remains LEGACY; no handover or execution capability is introduced.
