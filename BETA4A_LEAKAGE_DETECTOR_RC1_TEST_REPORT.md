# Beta 4A M4 Leakage Detector RC1 Test Report

Date: 2026-07-23
Release status: AUDIT_CANDIDATE

## Implemented checks

- Temporal consistency using supplied lineage timestamps.
- Fail-closed handling for missing temporal lineage evidence.
- Cross-bundle duplicate dataset-row identity detection.
- Shared structural-group detection across Train/Validation/Test.
- Raw Pearson feature/label correlation diagnostics as warning only.
- Deterministic canonical SHA-256 sealing of LeakageDetectionReport.
- Downstream `require_pass()` hard-block gate.

## Verification executed

- Focused Beta 4A suite: **35 passed**.
- Full repository regression: **1158 passed**.
- Python compile verification: **PASS**.

Commands:

```bash
PYTHONPATH=. pytest -q tests/test_beta4a_leakage_detector.py \
  tests/test_beta4a_dataset_split.py \
  tests/test_beta4a_model_evaluation_gate.py \
  tests/test_beta4a_model_lifecycle_gate.py \
  tests/test_beta4a_scaffolding.py

PYTHONPATH=. pytest -q
PYTHONPATH=. python -m compileall -q dvs_ai/beta4a tests/test_beta4a_leakage_detector.py
```

## Scope boundary

M4 verifies supplied evidence only. It does not recompute indicators, quality,
coverage, burn-in, labels, feature mathematics, or lineage timestamps.
Correlation findings are descriptive warnings and never remove features.
