# DVS AI Alpha 3.0.5 — Selection Projection Hardening

## Implemented

- Added a persistent `CURRENT` coin badge driven by the shared `SelectionState`.
- Added `_sync_views_to_selection()` as the single UI projection path for History, Paper Trade and Smart Money.
- Smart Money now explicitly re-renders the selected analysis when a tab is activated; blocked Qt signals no longer leave stale detail content visible.
- Restored rows are automatically scrolled to the center in History, Paper Trade and Smart Money.
- Preserved the existing fail-closed trading boundaries: DATA LIVE, ORDERS LOCKED.

## Verification

- `python -m compileall -q dvs_ai`: PASS
- Focused v3.0.5 regression tests: 4 passed

## Runtime verification requested on Windows

1. Select `1000BONK/USDT` in Signal History.
2. Open Smart Money and verify the narrative is also for `1000BONK/USDT`.
3. Open Paper Trade and verify a matching row is highlighted and scrolled into view when present.
4. Confirm the `CURRENT:` badge remains unchanged across tabs.
