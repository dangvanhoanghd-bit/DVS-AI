# Beta 4A RC3 Repair Report

Status: AUDIT_CANDIDATE (not Audit Verified)

## Repairs implemented

1. Holdout isolation
   - Pipeline materializes only TRAIN and VALIDATION feature partitions.
   - TEST partition is empty in the pipeline FeatureMatrixArtifact.
   - Trainer receives TrainingFeatureMatrixArtifact, which has no `test` attribute.
   - Locked Test rows remain loaded only through ModelEvaluationGate's TestRowLoader.

2. Trained model artifact binding
   - Added TrainedModelArtifact.
   - Model binary SHA-256, feature matrix SHA-256, training configuration SHA-256 and training run ID are sealed into the ModelSlot manifest.
   - EvaluationReport carries the same identities.
   - ModelLifecycleGate blocks mismatched model, matrix or training run identities.

3. Locked Test history hardening
   - LockedTestRowRegistry.rebuild() now checks TEST-vs-TRAIN, TEST-vs-VALIDATION and TEST-vs-TEST conflicts across split artifacts.

4. Dataset schema marker
   - DATASET_SCHEMA_VERSION bumped from beta3b.dataset.v1 to beta4a.dataset.v2.

5. Effective model state projection
   - Added read-only resolve_effective_model_state().
   - Lifecycle VALIDATED evidence wins over the derived ModelRegistry state without creating a second mutable source of truth.

6. Qt worker/UI thread repair
   - Replaced worker failure lambdas that created QMessageBox in the worker thread with QObject receiver slots on the GUI widget.
   - Research Cohort now validates at least two Experiment IDs before dispatch.
   - Research Cohort worker load() now catches and emits exceptions.
   - Research Cohort thread shutdown is handled through shutdown()/closeEvent().
   - Applied the same GUI-thread error-slot pattern to the related Research/Governance widgets found by audit.

## Verification

- Beta 4A focused tests: 54 passed
- Full repository tests: 1177 passed
- Python compileall: PASS
- Remaining `failed.connect(lambda ... QMessageBox.warning...)` patterns: 0

## Release decision

This build remains AUDIT_CANDIDATE. Independent re-audit is required before applying BETA4A_AUDIT_VERIFIED.
