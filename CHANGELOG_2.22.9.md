# Alpha 2.22.9 — Debounced Aggregate Refresh

- Removed direct per-result aggregate-panel rebuilds.
- Added 200 ms trailing-edge debounce.
- Preserved immediate dashboard-row updates.
- Guaranteed one final aggregate refresh at scan completion.
- Debounced error refreshes through the same path.
- Made error-table rebuilding atomic.
- Added profiler timing for `aggregate_refresh_debounced`.
- Preserved Qt Slot decorators.
- No trading or analysis logic changed.
