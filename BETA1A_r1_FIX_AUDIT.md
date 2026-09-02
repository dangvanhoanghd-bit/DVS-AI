# Beta 1A r1 — Feature Snapshot Wiring Fix

## Root cause fixed
The live pipeline created `EvaluationCapture` without `feature_snapshot`, so the immutable snapshot writer was never reached.

## Changes
- `LiveEpisodeCapture.capture()` computes one trace and reuses it for both the immutable candidate snapshot and the diagnostic trace.
- Empty dataset exports now raise `NoLearningSamplesError` before creating files.
- `EXPORT_LEARNING_DATASET.py` reports `LEARNING_DATASET_NOT_GENERATED` with resolved/snapshot/ready counts.
- Added behavioral regression tests for live snapshot wiring and empty-export handling.

## Frozen boundaries
Decision Engine, confidence formula, thresholds, MAIN/SHADOW policy, Quantum governance, and execution authority are unchanged.
