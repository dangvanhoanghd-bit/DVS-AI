# Beta 4A ModelEvaluationGate RC1 — Test Report

## Environment

- Execution date: 2026-07-23
- Test command: `PYTHONPATH=<repository-root> pytest -q`
- Compile command: `python -m compileall -q dvs_ai tests`

## Results

- Focused Beta 4A tests: **14 passed**
- Full repository regression: **1137 passed**
- Compile verification: **PASS**

## Behavioral coverage

- First evaluation qualifies; later evaluations are historical-only.
- Access marker exists before Test loader receives rows.
- Failure after access consumes holdout fail-closed.
- Concurrent evaluator cannot create a second qualifying report.
- Active unexpired claim is refused.
- Expired claim without access is recovered with `EXPIRED_CLAIM_RECOVERED`.
- Every completed test claim has one terminal outcome.
