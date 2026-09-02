# Beta 4A Dataset Split Engine — Frozen Implementation Contract

## Scope

The Dataset Split Engine operates on `dataset_row_id` records from one selected cumulative Dataset Bundle. It reads already-produced timestamps and identities and never recomputes lower-layer coverage, quality, burn-in, lineage validity, or other scientific metrics.

## Frozen behavior

- Temporal walk-forward only; no random shuffle.
- Deterministic ordering by `(close_time, dataset_row_id)`.
- Candidate ownership interval is `[setup_time, close_time]`.
- Any interval crossing a Train/Validation or Validation/Test boundary is purged.
- Embargo is applied independently after each boundary and counted separately from purge.
- One immutable `structural_group_id` cannot span partitions. A crossing group is conservatively excluded in full.
- Rows already present in `LockedTestRowRegistry` are excluded before boundary calculation.
- Independent sample floors are enforced for Train, Validation, and Test.
- Test begins as `LOCKED_UNCONSUMED`.
- Split artifacts are deterministically identified by a canonical SHA-256 payload.

## Derived registry

`LockedTestRowRegistry` is rebuilt only from immutable Split Artifacts and Holdout Consumption Records. It is never primary truth.

- Test rows without a matching consumption record become `LOCKED_UNCONSUMED`.
- Test rows whose split has a matching consumption record become `CONSUMED`.
- A row appearing as Test in multiple split artifacts raises `LOCK_HISTORY_CONFLICT`.
- A consumption record referencing an unknown split raises `SPLIT_ARTIFACT_VERIFICATION_FAILED_EXCLUDED`.

## Status and hard-block codes

- `INVALID_SPLIT_TIMESTAMP`
- `INVALID_CANDIDATE_INTERVAL`
- `SPLIT_ROW_SCHEMA_MISMATCH`
- `DUPLICATE_DATASET_ROW_ID`
- `SPLIT_SAMPLE_FLOOR_NOT_MET`
- `LOCK_HISTORY_CONFLICT`
- `SPLIT_ARTIFACT_VERIFICATION_FAILED_EXCLUDED`
