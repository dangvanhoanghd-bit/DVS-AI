# M5.1 Test Report

Executed on the extracted M4 baseline.

- `python -m compileall -q dvs_ai/scientific`: PASS
- `python -m pytest -q tests/test_m5_scientific_contracts.py`: 7 passed
- `python -m pytest -q`: 537 passed

Covered cases:
- immutable evidence records and read-only metadata;
- quality range validation;
- hard-gate anti-compensation invariant;
- duplicate validation metric rejection;
- registered-model certification requirement;
- end-to-end trace linkage;
- strict lifecycle transitions.
