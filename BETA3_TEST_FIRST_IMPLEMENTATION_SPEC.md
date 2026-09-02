# Beta 3 Test-First Implementation Specification

Status: BETA 3A IMPLEMENTED — FOUNDATION PROJECTION ONLY

## Implemented scope

Beta 3A introduces a read-only, governed foundation above `UnifiedOutcomeService.learning_ready()`:

1. `PolicyIdentity` reuses QG-13 identity fields.
2. `LearningCandidateBuilder` accepts only the existing unified learning-ready contract.
3. `FeatureStoreProjector` projects the existing evidence snapshot and verifies its declared SHA-256.
4. `classify_dataset_readiness()` reuses 30/100/300/500 exactly.
5. `lineage_record()` traces each feature row to unified/source/snapshot/policy identity.

## Explicitly not implemented

- No model training.
- No predictive inference.
- No threshold or Decision Engine mutation.
- No SQLite reads in the Beta 3A module.
- No third snapshot table or writer.
- No dataset bundle emission yet.
- No Insight Generator yet.

## Test-first gates

The implementation is accepted only when tests prove:

- fewer than 30 qualified samples is `UNOBSERVABLE` and cannot emit a dataset;
- explicit automatic resolution does not require Human Review;
- `EXCLUDE` never enters Learning;
- missing or mismatched snapshot hashes are rejected;
- policy identity is present on every feature row;
- lineage is complete;
- the module contains no direct SQLite dependency.
