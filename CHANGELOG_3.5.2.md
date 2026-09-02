# DVS AI Alpha 3.5.2 — Qualification Evidence Center

## Added
- Read-only Qualification Evidence Center in Decision Core.
- Filter by symbol and canonical agreement code.
- Evidence detail view with Legacy/Unified actions, confidence, regime, phase, timeframe, reason codes, event names, synthetic ledger status, profile hash, ledger hash and evidence hash.
- JSON and CSV evidence export.
- SHA-256 evidence sealing for every newly recorded shadow observation.
- Integrity statuses: `PASS`, `FAILED`, and `LEGACY_UNSEALED` for pre-3.5.2 rows.
- SQLite schema migration for evidence fields without deleting existing qualification data.

## Safety
- Unified Core remains shadow-only.
- Exposed quantity remains zero.
- Paper authority remains Legacy.
- No authority activation, promotion, exchange, testnet or LIVE-order capability was added.

## Verification
- Python compileall: PASS.
- Full regression suite: 668 passed.
