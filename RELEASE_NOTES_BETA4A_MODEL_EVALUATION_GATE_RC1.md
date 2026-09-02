# Beta 4A ModelEvaluationGate RC1 — Release Notes

Status: **AUDIT_CANDIDATE**

This release implements the first production Runtime Gate from the Beta 4A Design Freeze.

## Implemented

- SQLite-backed atomic qualifying claim using `BEGIN IMMEDIATE`.
- Exactly one qualifying evaluation per Split.
- Separate evaluation modes:
  - `QUALIFYING_HOLDOUT_EVALUATION`
  - `HISTORICAL_BENCHMARK_EVALUATION`
- `HOLDOUT_ACCESS_STARTED` persisted before Test rows are returned to evaluator code.
- Fail-closed behavior when loading/evaluation fails after access begins.
- Immutable-style persisted Evaluation Report and Holdout Consumption Record payloads with SHA-256 identities.
- Claim ownership checks before qualifying artifact publication.
- Stale claim recovery when Test access provably never began.
- `EXPIRED_CLAIM_RECOVERED` audit event.
- Expired claims after access are terminated as `CLAIM_ABORTED_AFTER_ACCESS` and remain consumed.
- Read-only `audit_snapshot()` for audit and behavioral verification.

## Explicit boundary

The Runtime Gate is an application architecture and audit control. It is not a filesystem ACL, encryption boundary, or operating-system sandbox.

## Not included

- ModelLifecycleGate production implementation.
- Dataset Split production implementation.
- LockedTestRowRegistry rebuild implementation.
- Feature Matrix Builder production implementation.
