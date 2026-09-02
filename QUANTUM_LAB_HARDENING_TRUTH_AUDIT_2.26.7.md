# DVS AI Alpha 2.26.7 — Quantum Lab Hardening Truth Audit

## Truth rules

Quantum training accepts a closed determinate PAPER trade only when its signal-time snapshot declares:

- `schema = DVS_QUANTUM_TRAINING_V1`
- `calibration_state = VALIDATED`
- `drift_state = STABLE`
- `order_flow_quality = FULL`
- all five evidence families are available and contain finite score/quality values

Rows marked `WATCH`, `DRIFT`, `DEGRADED`, `BLOCKED`, rejected calibration, malformed snapshot, or legacy/no snapshot are excluded and counted by reason.

## Shadow safety

The optimizer no longer writes `config.json`. A successful recommendation can only create `data/quantum_shadow_candidate.json`, which requires separate human review. Direct `apply_shadow_only()` is disabled. MAIN remains immutable.

## Scope

This release hardens data eligibility and candidate promotion. It does not optimize Evidence Fusion weights, change PAPER gates, size positions, or connect to Execution.
