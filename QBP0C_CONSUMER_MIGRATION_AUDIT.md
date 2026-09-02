# QBP-0C Consumer Migration Audit

## Implemented scope

The Quantum read path now converges through `QuantumDataAdapter` for the first runtime consumers:

- `QuantumOptimizer._load_closed()`
- `CandidateBacktestService` indirectly through the optimizer
- `QuantumReadinessService.snapshot()`

No storage migration, schema change, write-path change, Decision Engine change, threshold tuning, MAIN authority, or execution authority was introduced.

## Data path

`PaperTradeSource` and `EpisodeOutcomeSource` produce immutable `UnifiedOutcome` records. The adapter combines these records with source-qualified identities. Optimizer and readiness consumers no longer issue direct `paper_trades` SQL.

## Legacy equivalence and mapping

Explicit legacy mappings now include:

- `TP2 -> WIN`
- `STOP -> LOSS`
- `SL -> LOSS`
- `INVALID -> LOSS`
- `PARTIAL_STOP -> WIN/LOSS` using an explicit, centralized realized-R sign rule
- ambiguous and expired states retain their governed mappings

`PARTIAL_STOP` is the only conditional mapping. Its rule ID is preserved in provenance as `LEGACY_PARTIAL_STOP_R_SIGN_V1`.

## Eligibility behavior

Only determinate `WIN` / `LOSS` records continue to optimizer/readiness quality qualification. Records still require a valid `DVS_QUANTUM_TRAINING_V1` snapshot, `VALIDATED` calibration, `STABLE` drift, and `FULL` order-flow quality. Episode outcomes without the required training snapshot fail closed and are counted as missing snapshot rather than silently admitted.

## Tests

- Added `tests/test_qbp0_consumer_migration.py`.
- Full suite: 879 passed.
- Compileall: passed.

## Frozen Decision Engine

- MD5: `72cf7d54e1ed6369400683358da8c0ef`
- SHA-256: `00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce`
