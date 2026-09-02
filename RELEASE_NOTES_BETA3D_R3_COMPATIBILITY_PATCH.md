# DVS AI Alpha 4.3.0E-3 — Beta 3D-r3 Compatibility Patch

## Purpose

Additive pre-Beta4 lineage compatibility only. No Beta 3 decision, promotion,
registry, quality, burn-in, or cross-bundle behavior is changed.

## Added lineage fields

- `first_eligible_evaluation_timestamp`
- `snapshot_timestamp`

The fields are propagated from the governed `UnifiedOutcomeRecord.setup_time`
value already exposed by the Beta 2 read contract. The patch does not derive,
recalculate, or substitute a timestamp when source truth is absent; both fields
remain `null` in that case.

The fields are emitted at both levels of `lineage_index.jsonl`:

1. dataset-row lineage record;
2. nested feature-row lineage record.

## Compatibility guarantees

- Existing constructor call sites remain valid because both new candidate fields
  are optional and additive.
- Existing Beta 3 bundle verification remains backward compatible.
- Dataset and manifest schema version identifiers are unchanged.
- Existing Beta 3D ranking and promotion behavior is unchanged.
- No Beta 4 split, leakage, holdout, model evaluation, or model registry logic is
  included in this patch.

## Verification

- Full regression: `1123 passed`.
- Focused Beta 3A–3D and attack/quality suite: `116 passed`.
- Python compile verification: PASS.
