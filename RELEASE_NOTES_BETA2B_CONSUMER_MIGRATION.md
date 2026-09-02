# DVS AI Beta 2B — Unified Outcome Consumer Migration

## Scope

Beta 2B migrates the default read paths for Learning, Quantum Optimizer and Quantum Readiness to `UnifiedOutcomeService`.

## Architectural changes

- `LearningService` no longer contains direct `FROM paper_trades` analytics queries.
- `QuantumOptimizer` defaults to `UnifiedOutcomeService.learning_ready()`.
- `QuantumReadinessService` defaults to `UnifiedOutcomeService.learning_ready()`.
- `QuantumDataAdapter` remains unchanged as a raw, no-cross-source-dedup convergence adapter.
- Automatic merge remains limited to explicit cross-source identity.
- `candidate_id`, `outcome_id`, and `decision_id` are now exposed as provenance where present.
- Soft fingerprints remain review-only and cannot create learning/Quantum samples.

## Legacy compatibility

A schema-gated compatibility path remains only for pre-unified databases. Every use emits `LEGACY_SQL_PATH_USED` telemetry. The path is disabled whenever the full Beta 2 pipeline schema exists.

This implements the agreed sequence:

`Deprecate → Audit → Remove`

## Safety boundary

No Decision Engine logic, thresholds, execution authority, MAIN/SHADOW authority, or automatic tuning behavior was changed.
