# DVS AI Alpha 2.25.5 — Order Flow Runtime Integration Audit

## Verified implementation
- Application owns one `OrderFlowRuntime`.
- Collector, controlled backfiller, persistent store, and MicrostructureService share the same store.
- Runtime starts after application construction and closes in both `MainWindow.closeEvent` and the app `finally` block; close is idempotent.
- Collector diagnostics are passed directly into the data-quality gate.
- UI status badge shows collector state, message age, unresolved gaps, and liquidation warnings.
- Runtime remains public-market-data evidence only and has no Execution imports.

## Explicit limitations
- Subscriptions are fixed at startup from the configured watchlist.
- A collector connection failure does not abort the desktop application; quality gate fails closed.
- This release does not guarantee lossless market data, dynamic subscriptions, or liquidation backfill.
- LIVE execution remains disabled.
