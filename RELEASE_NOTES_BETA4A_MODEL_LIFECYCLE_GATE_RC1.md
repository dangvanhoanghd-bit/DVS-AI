# Beta 4A ModelLifecycleGate RC1 — Release Notes

Status: **AUDIT_CANDIDATE**

## Scope

This release implements the frozen Beta 4A `ModelLifecycleGate` contract for the transition:

`TRAINED_UNVALIDATED -> VALIDATED`

It builds on the ModelEvaluationGate RC1 baseline and does not alter Beta 3 decision, promotion, registry, burn-in, or quality behavior.

## Enforced gates

Promotion to `VALIDATED` now requires all of the following:

- `evaluation_mode == QUALIFYING_HOLDOUT_EVALUATION`
- `qualifying == true`
- `historical_benchmark_only == false`
- `test_status_at_evaluation_start == LOCKED_UNCONSUMED`
- an existing `HoldoutConsumptionRecord`
- valid consumption-record SHA-256
- matching model-slot identity
- matching split identity
- qualifying evaluation purpose
- cryptographic binding from the consumption record to the EvaluationReport core payload
- source Model Slot state `TRAINED_UNVALIDATED`

Historical benchmark reports are hard-blocked and cannot validate a Model Slot.

## Atomic lifecycle publication

The source manifest, target `VALIDATED` manifest, and immutable lifecycle transition record are persisted inside one SQLite `BEGIN IMMEDIATE` transaction.

A second `VALIDATED` transition for the same Model Slot is refused.

## Audit trail

`audit_snapshot(model_slot_id)` exposes persisted manifests and lifecycle transitions for independent verification.

## Runtime boundary

This Gate is an application-architecture and audit control. It is not an operating-system filesystem security boundary.
