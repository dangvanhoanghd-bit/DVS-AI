# Data Pipeline Integrity Truth Audit — Alpha 2.32.5-r2

## Scope

- Idempotent write boundary for `shadow_observations`.
- Audited migration of exact duplicate historical rows.
- PAPER runtime diagnostics for evaluated/eligible/created/blocked states.
- QTableWidget ownership warning regression fix.

## Safety boundary

This release does not change Decision Engine, confidence thresholds, Quantum, MAIN promotion, Testnet, or LIVE execution.

## Migration behavior

Existing exact duplicates are merged into a canonical row, preferring the row with outcome and paper-trade linkage. Removed rows are serialized to `shadow_observation_duplicate_archive` before deletion. The standalone migration command creates a full database backup first.
