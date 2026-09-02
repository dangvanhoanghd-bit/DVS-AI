# DVS AI Alpha 2.26.3 — Adaptive Confidence Truth Audit

## Scope
This release adds an observe-only context adaptation layer on top of the validated PAPER probability from 2.26.1.

## Truth-verified behavior
- `confidence_score` remains the decision score used by existing PAPER gates.
- `adaptive_probability` is a separate annotation and cannot change entry status, thresholds, position size, or execution.
- Context is `(direction, market regime)` and uses only determinate CLOSED PAPER outcomes ordered chronologically.
- Context adaptation uses Bayesian shrinkage toward the global calibrated probability.
- Adjustment is bounded to ±8 percentage points.
- A chronological holdout rejects context adaptation when Brier score is worse than the global calibration by more than 0.005.
- Missing samples, invalid numbers, or unvalidated global probability fail closed.

## Explicit limitations
- No automatic threshold learning.
- No symbol-specific adaptation.
- No live outcome learning.
- No execution dependency.
- Context probability is observe-only and should not be described as a live trading trigger.
