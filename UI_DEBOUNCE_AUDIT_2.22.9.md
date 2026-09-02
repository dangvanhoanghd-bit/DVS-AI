# DVS AI Alpha 2.22.9 — Debounced Aggregate Refresh

## Confirmed root cause

`on_result()` executes once for each completed coin. It previously rebuilt the
error table and all aggregate summary panels after every result. Because
`refresh_summary()` repeatedly sorts and scans a growing result collection, the
total UI workload grows approximately quadratically during a scan.

`UIGeometryManager.schedule_view_restore()` runs only at scan completion and is
not part of this per-coin hot path.

## Fix

- Added a 200 ms single-shot trailing-edge debounce timer.
- Per-coin `_upsert_row()` remains immediate.
- Market Brief, Top Long/Short, pulse cards and error table are coalesced.
- `on_error()` uses the same debounce path.
- Scan completion forces one final flush, so the last update cannot be lost.
- Error-table rebuilding is atomic.
- `@Slot(object)` remains directly attached to `on_result()`.
- `@Slot(str, str)` remains directly attached to `on_error()`.

No trading or analysis logic changed.
