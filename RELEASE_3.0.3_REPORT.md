# DVS AI Alpha 3.0.3 — Selection State Foundation

## Scope

This stabilization release introduces the first shared selection layer for the
Unified Core desktop UI. It does not modify Decision, Risk, Paper execution,
Exchange, Deployment, or Live-order locks.

## Implemented

- Added a Qt-independent `SelectionState` and immutable `SelectionSnapshot`.
- Dashboard selection now updates the shared symbol/timeframe context.
- Smart Money row selection now updates `current_analysis`, Truth Dashboard,
  header symbol and the corresponding Dashboard row without recursive renders.
- Smart Money refresh prefers the shared selected symbol, preserving the user's
  cross-tab context when scan results are rebuilt.
- Added regression tests for symbol normalization, revision behavior and UI
  wiring.

## Safety

- No live order path added.
- `DATA LIVE · ORDERS LOCKED` remains unchanged.
- Selection synchronization is UI state only.

## Verification

- `python -m compileall -q dvs_ai`: PASS
- Full regression suite: 593 PASS, 13 FAIL
- All 13 failures are stale release-identity assertions hard-coded to versions
  2.32.0, 2.32.5, or 3.0.2; no functional regression failure was observed.
- New 3.0.3 focused tests: 4 PASS.
