# Milestone 1.2 — Test Report

## Commands

```text
python -m compileall -q dvs_ai
python -m pytest -q tests/test_integration_scientific_backend_bridge.py
python -m pytest -q
```

## Results

- Integration Bridge tests: **9 passed**
- Full GUI regression suite: **516 passed**
- Python package compilation: **PASS**

## Covered scenarios

- Valid configured root.
- Missing configured root with visible snapshot fallback.
- Configured root missing a required artifact.
- Configured root containing invalid JSON.
- Configured root failure with no packaged snapshot.
- Non-fail-closed safety remains degraded.
- Failed tests cannot be compensated by other green fields.
