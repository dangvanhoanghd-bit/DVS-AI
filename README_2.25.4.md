# DVS AI Alpha 2.25.4 — Order Flow Data Quality Gate

Run the verified release gate:

```bash
python release_gate_2_25_4.py
```

Expected result:

```text
346 passed
RELEASE GATE 2.25.4: PASS
```

This release classifies order-flow evidence as FULL, DEGRADED, or BLOCKED and prevents stale, unresolved-gap, bootstrap-only, or liquidation-incomplete data from receiving the same confidence as complete realtime evidence.

LIVE execution remains disabled.
