# DVS AI Alpha 2.32.5-r5 — Operational UX & Evidence Journey

Observe-only UX upgrade over r4.

## Changes
- Learning closed-trade card now separates closed, total PAPER, open and Quantum-eligible counts.
- Truth Dashboard shows `LEARNING` when the low health score is caused by insufficient evidence, while preserving real `CRITICAL` states for runtime/integrity faults.
- Shadow Observation shows `COLLECTING EVIDENCE` or `QUALITY GATE WAITING` instead of a misleading generic `BLOCKED` state when the pipeline is operating normally.
- Added AI Journey timeline: PAPER → Calibration → Reliability → Quantum → Shadow Promotion → MAIN.
- Added AI Health History and cumulative Evidence Outcome charts.
- No Decision, Confidence, Quantum optimization, Promotion, Testnet or Execution logic changed.
