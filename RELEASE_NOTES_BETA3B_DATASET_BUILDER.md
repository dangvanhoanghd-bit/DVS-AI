# Release Notes — Beta 3B Dataset Builder and Self-Sealed Manifest

## Added

- `dvs_ai/services/beta3_dataset_bundle.py`
  - `DatasetBuilder`
  - `DatasetBundleVerifier`
  - immutable dataset identifiers
  - policy/extractor identity gates
  - burn-in release gate
  - deterministic dataset and lineage generation
  - SHA-256 component verification
  - self-sealed manifest and bundle identity
  - rollback parent linkage

- `tests/test_beta3b_dataset_bundle.py`
  - 29 independent implementation tests

## Dataset bundle contract

A released bundle contains exactly:

- `training_dataset.jsonl`
- `exclusions.jsonl`
- `quality_report.json`
- `lineage_index.jsonl`
- `dataset.manifest.json`

Below 30 qualified samples the builder returns `UNOBSERVABLE` and emits no dataset bundle.

## Safety boundary

Beta 3B does not train a model, generate trading insights, access SQLite directly, or modify the Decision Engine.
