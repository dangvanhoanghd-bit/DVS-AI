# DVS AI Alpha 2.26.1 — Probability Calibration Truth Audit

## Truth conclusion

`confidence_score` is a bounded decision-quality score, not a statistically calibrated probability.
Alpha 2.26.1 adds a separate `calibrated_probability` derived only from determinate CLOSED PAPER trades.

## Method

- chronological train/validation split (no random leakage)
- Bayesian-smoothed confidence buckets
- monotonic Pool Adjacent Violators (PAV)
- out-of-sample Brier score and ECE release gate
- fail closed on insufficient data or rejected validation

## Safety boundary

Calibration is annotation-only. It does not modify entry status, eligibility, thresholds, Paper Trade gates, position sizing, or Execution.

## Known limitations

- uses PAPER outcomes, not live fills
- bucket calibration, not per-regime hierarchical calibration
- no automatic threshold or weight learning
- model is refit at scan finalization and remains observe-only unless validated
