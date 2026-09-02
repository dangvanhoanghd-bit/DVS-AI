# DVS AI Alpha 3.0.6 — Smart Entry Projection Fix

## Fixed
- Smart Entry now renders the currently selected symbol when selection originates from Paper Trade, Signal History, Smart Money, or another synchronized tab.
- Added a dedicated Smart Entry renderer that does not force navigation, repaint the full detail view, or reset scroll/timeframe state.
- Shared selection now resolves the matching cached analysis before projecting Smart Entry.
- Full detail rendering reuses the same Smart Entry renderer to avoid duplicated UI logic.

## Safety
- No changes to Decision Engine, Risk Gate, Paper execution logic, Exchange, Testnet, Deployment, or LIVE order paths.
- Execution state remains DATA LIVE · ORDERS LOCKED.

## Verification
- Python compileall: PASS
- Focused regression tests: 10 passed
