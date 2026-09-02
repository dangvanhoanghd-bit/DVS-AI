# Beta 4A Dataset Split Engine RC1 — Release Notes

Status: `AUDIT_CANDIDATE`

This release implements M3 Dataset Split Engine and the derived Locked Test Row Registry on top of the Beta 4A ModelLifecycleGate RC1 candidate.

## Added

- `DatasetRowRecord`
- `SplitConfig`
- deterministic `DatasetSplitEngine.split()`
- temporal walk-forward partitioning
- purge and separate embargo accounting
- structural-group boundary protection
- prior locked/consumed Test-row exclusion
- independent partition sample floors
- deterministic Split Artifact SHA-256 identity
- `LockedTestRowRegistry.rebuild()`
- conflict and orphan-consumption hard blocks
- seven focused M3 tests

## Verification

- Beta 4A focused tests: 28 passed
- Full repository regression: 1151 passed
- Python compile verification: PASS

No Audit Verified claim is made by this release.
