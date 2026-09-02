# DVS AI Alpha 3.0.4 — Cross-Tab Selection Sync

## Implemented
- Added shared symbol selection propagation from Signal History and Paper Trade.
- Restores the shared symbol after History, Paper Trade, and Smart Money table refreshes.
- Restores selection when switching tabs.
- Uses existing analysis context when available; otherwise preserves symbol-only state safely.
- Keeps dashboard selection, header symbol, Truth Dashboard, and Smart Money context aligned.

## Safety boundary
- No changes to Decision Engine, Risk Gate, Paper execution logic, Exchange, Deployment, Testnet, or LIVE order paths.
- Execution status remains DATA LIVE · ORDERS LOCKED.

## Validation
- Python compileall: PASS.
- Focused v3.0.4 tests: 4 passed.
