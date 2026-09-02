# DVS AI Alpha 2.25.1 — Persistent Order Flow Foundation Audit

## Scope

This release adds a passive, persistent order-flow boundary. It does **not**
start a WebSocket, place orders, or enable LIVE execution.

## Implemented

- SQLite/WAL event store for aggregate trades and force-order events.
- Stable event keys and `INSERT OR IGNORE` deduplication.
- Binance `aggTrade` aggressor-side interpretation (`m=true` => aggressive SELL).
- Binance `forceOrder` mapping: SELL liquidates longs; BUY liquidates shorts.
- Persistent cumulative CVD within the configured retention horizon.
- Five-minute flow window with CVD velocity normalized before Position Building.
- Explicit data quality: `EMPTY`, `BOOTSTRAP`, or `REALTIME`.
- Fail-closed rejection of NaN, incomplete, non-positive and malformed events.
- Thread-safe ingestion and reads, bounded retention, and diagnostics.

## Truth limitations

- No network collector is started in this release.
- REST `aggTrades` are explicitly marked `BOOTSTRAP`, not realtime.
- `REALTIME` is only set when a caller feeds realtime events.
- CVD persistence is bounded by retention; it is not an exchange-global lifetime CVD.
- Liquidation data remains empty until force-order payloads are ingested.
- This remains an evidence layer and cannot create or execute a trade.

## Verification

- Repository compile: PASS
- Targeted order-flow tests: 4/4 PASS
- Full suite: 333/333 PASS
