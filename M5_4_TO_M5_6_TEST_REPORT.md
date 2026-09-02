# M5.4–M5.6 Test Report

Command:

`PYTHONPATH=<project_root> python -m pytest -q`

Result:

`556 passed in 13.60s`

Additional compile verification:

`python -m compileall -q dvs_ai`

Result: PASS

New test coverage includes:

- complete registry coverage for contract codes
- duplicate reason-code rejection
- strict rejection of unregistered reason codes
- successful explainability narrative generation
- failure reason mapping
- successful deterministic replay
- tamper detection during replay
