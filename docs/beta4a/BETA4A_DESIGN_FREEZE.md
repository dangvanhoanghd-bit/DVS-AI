# Beta 4A Design Freeze

Status: FROZEN FOR SCAFFOLDING

Beta 4A prepares governed data for real ML. It reads, verifies, and propagates lower-layer facts; it never recomputes lower-layer coverage, quality, burn-in, or lineage validity.

## Frozen modules

1. Bundle Selection
2. Feature Matrix Builder
3. Dataset Split
4. Leakage Detector
5. Dataset/Artifact Packaging
6. Model Registry

## Frozen runtime gates

- `BundleSelectionGate`: sole Beta 4A entry point for selecting one cumulative `TRAINING_CANDIDATE` bundle.
- `ModelEvaluationGate`: sole application entry point allowed to claim and open Test payloads.
- `ModelLifecycleGate`: sole application entry point for Model Slot transitions.

## Holdout policy

Test states are `LOCKED_UNCONSUMED` and `CONSUMED`. The first qualifying access atomically claims the holdout, persists `HOLDOUT_ACCESS_STARTED` before payload exposure, and creates an immutable `HoldoutConsumptionRecord`. A consumed holdout may be evaluated only as a non-qualifying historical benchmark.

Validation is intentionally recyclable across split generations. Test is permanently locked across generations.

## Runtime enforcement boundary

Runtime Gates are application-architecture and audit controls. They are verified by behavioral tests, artifact provenance, and static searches. They are not filesystem ACLs, encryption, or an operating-system security boundary.

## Fail-closed rule

When the system cannot prove that Test payload access never started, the holdout is treated as consumed.

## Claim completeness

Every claim must terminate as exactly one of:

- `CLAIM_COMPLETED`
- `CLAIM_RECOVERED` with `EXPIRED_CLAIM_RECOVERED`
- `CLAIM_ABORTED_AFTER_ACCESS` with `HOLDOUT_CONSUMED_WITHOUT_COMPLETED_EVALUATION`

No claim may disappear from history.
