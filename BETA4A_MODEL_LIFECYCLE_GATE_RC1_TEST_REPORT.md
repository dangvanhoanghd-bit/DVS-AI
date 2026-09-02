# Beta 4A ModelLifecycleGate RC1 — Test Report

Status: **AUDIT_CANDIDATE**

Execution environment: repository root with `PYTHONPATH=.`

## Focused Beta 4A tests

Command:

```bash
PYTHONPATH=. pytest -q \
  tests/test_beta4a_model_lifecycle_gate.py \
  tests/test_beta4a_model_evaluation_gate.py \
  tests/test_beta4a_scaffolding.py
```

Result:

```text
21 passed
```

## Full repository regression

Command:

```bash
PYTHONPATH=. pytest -q
```

Result:

```text
1144 passed
```

## Compile verification

Command:

```bash
python -m compileall -q dvs_ai tests
```

Result: PASS

## Covered lifecycle invariants

- qualifying report can promote exactly once
- historical benchmark is hard-blocked
- only `TRAINED_UNVALIDATED` can promote
- model-slot/report identity must match
- source split/report split must match
- HoldoutConsumptionRecord must exist
- HoldoutConsumptionRecord SHA-256 must match payload
- consumption record must bind to EvaluationReport core hash
- duplicate VALIDATED transition is refused
- source/target manifests and transition artifact are persisted
