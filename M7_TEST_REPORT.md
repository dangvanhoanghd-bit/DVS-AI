# M7 Test Report

## Focused M7 tests
- Command: `PYTHONPATH=<project_root> python -m pytest -q tests/test_m7_paper_risk_analytics.py`
- Result: **9 passed**

## Full regression suite
- Command: `PYTHONPATH=<project_root> python -m pytest -q`
- Result: **570 passed in 5.42s**

## Compile check
- Command: `PYTHONPATH=<project_root> python -m compileall -q dvs_ai`
- Result: **PASS**

## Covered M7 behavior
- Long and short PnL symmetry.
- Fees and cash-balance accounting.
- Unauthorized-decision fail-closed behavior.
- Position sizing reduction.
- Kill switch.
- Daily loss gate.
- Duplicate position protection.
- Equity and drawdown.
- Performance metrics.
