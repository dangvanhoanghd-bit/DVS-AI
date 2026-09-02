# DVS AI Alpha 2.22.2 — Fullscreen Layout Lock

The video showed a vertical layout snap after each completed scan.

Alpha 2.22.1 removed per-coin splitter resets, but one deferred `setSizes()`
still ran after every scan. In maximized mode it reapplied stale geometry.

A second conflict existed: MarketChart required at least 430 px while the detail
page capped it near 370 px. Qt had to redistribute the other panels differently
as content changed.

Fixes:
- Removed all scan-time splitter save/restore operations.
- Added a stable scroll viewport with permanent scrollbar reservation.
- Fixed deterministic heights for chart, timeframe table, narrative and plan.
- Removed the conflicting MarketChart minimum.
- No analysis or trading logic changed.
