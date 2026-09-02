# Beta 4A Dataset Split Engine RC1 — Test Report

## Commands

```bash
PYTHONPATH=. pytest -q tests/test_beta4a_*.py
PYTHONPATH=. pytest -q
python -m compileall -q dvs_ai tests
```

## Results

- Focused Beta 4A suite: `28 passed`
- Full repository suite: `1151 passed`
- Compile verification: `PASS`

## Focused M3 coverage

- deterministic temporal ordering
- locked Test initialization
- purge of boundary-overlapping intervals
- separate embargo accounting
- indivisible structural groups
- prior locked and consumed Test exclusions
- independent sample floors
- registry consumption-state derivation
- duplicate Test history conflict
