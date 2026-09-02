# DVS AI Alpha 2.26.8

- MAIN search dimensions hard-frozen.
- Shadow thresholds and Evidence Fusion family weights may be proposed only in a reviewable candidate.
- Candidate family weights are normalized and guardrailed.
- Drift and evidence reliability history are persisted in SQLite and charted in Truth Dashboard.
- Human approval remains mandatory; config and LIVE execution are not mutated.

Run: `python release_gate_2_26_8.py`
