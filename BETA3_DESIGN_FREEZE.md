# DVS AI Beta 3 Design Freeze — Adaptive Learning Foundation

Status: DESIGN FROZEN
Scope: data preparation, descriptive analysis, bias/quality diagnostics, governed insight generation
Out of scope: model training, threshold tuning, Decision Engine modification, execution authority

## Immutable safety boundary

Beta 3 does not train or deploy a predictive model. It cannot write to Decision Engine configuration, change thresholds, change confidence, place orders, or promote a policy. It produces governed datasets, diagnostics, and non-causal statistical insights only.

## Reused foundations — no parallel reinvention

1. Source truth remains `UnifiedOutcomeService` and its immutable evidence linkage.
2. Feature materialization is derived from the existing `feature_snapshot_hash`; Beta 3 creates no third operational snapshot source.
3. Policy identity reuses QG-13 scoped policy identity: `decision_engine_checksum` plus governed interacting parameters, excluding operational settings.
4. Burn-in reuses QBP-0E/QBP-1 thresholds exactly: 30 / 100 / 300 / 500 qualified samples.
5. Statistical validation reuses `HolmBonferroniController` and `DeterministicBootstrapValidator` from QBP-3.
6. Dataset packaging reuses canonical JSON plus self-sealing SHA-256 manifests.

## Eleven frozen design modules/documents

1. `LEARNING_FOUNDATION_SPEC.md`
2. `FEATURE_SNAPSHOT_SPEC.md`
3. `FEATURE_STORE_SCHEMA.md`
4. `DATASET_BUILDER_SPEC.md`
5. `DATASET_VERSIONING_SPEC.md`
6. `FEATURE_QUALITY_SPEC.md`
7. `LEARNING_CANDIDATE_RULES.md`
8. `LEARNING_ENGINE_SPEC.md`
9. `INSIGHT_GENERATOR_SPEC.md`
10. `SAFETY_LAYER_SPEC.md`
11. `LEARNING_DATA_LINEAGE.md`

## End-to-end architecture

```text
UnifiedOutcomeService.learning_ready()
        │
        ▼
LearningCandidateBuilder
        │  verifies terminal/snapshot/integrity/review semantics
        ▼
Existing immutable feature snapshot reference
        │  feature_snapshot_hash + source snapshot payload
        ▼
FeatureStore materialization
        │  policy-scoped, immutable, lineage-complete
        ▼
DatasetBuilder
        │  burn-in + quality + cohort checks
        ▼
Self-sealed Training Dataset Bundle
        │
        ├── Descriptive Learning Engine
        ├── Bias/coverage diagnostics
        └── Governed Insight Generator
```

## Readiness states

Beta 3 reuses project vocabulary and does not report empty success:

- `DATA_INTEGRITY_BLOCKED`
- `UNOBSERVABLE` (<30 qualified samples or zero valid feature rows)
- `DESCRIPTIVE_ONLY` (30–99)
- `RESEARCH_CANDIDATE_ONLY` (100–299)
- `VALIDATION_REVIEW_ELIGIBLE` (300–499)
- `BURN_IN_COMPLETE` (>=500)

These states authorize descriptive depth only. None authorizes model training, Decision Engine mutation, or execution.

## Review semantics

Human review is not mandatory for every sample. Automatic explicit-source identity resolution remains eligible. If a review event exists, it must be valid and fully applied. `EXCLUDE` always removes the sample. Unresolved conflict, ambiguous match, invalid review hash, or unapplied review blocks inclusion.

## Acceptance criteria before implementation

- Design attack review covers all eleven documents.
- Test specifications are written before production code.
- No new source-of-truth table is introduced.
- No new statistical controller duplicates QBP-3.
- No dataset is emitted as successful below the 30-sample observability threshold.
- Every dataset row has complete lineage to source identities, snapshot hash, and policy identity.
