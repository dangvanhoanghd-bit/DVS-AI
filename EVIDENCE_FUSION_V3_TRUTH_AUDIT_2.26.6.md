# DVS AI Alpha 2.26.6 — Evidence Fusion V3 Truth Audit

Evidence family weights are loaded from config.json. Explicit caller weights remain authoritative for tests and specialized use. Reliability modifies effective influence only when the PAPER reliability state is SHRUNK or VALIDATED; UNKNOWN is neutral. Source provenance reduces influence for PROXY/BOOTSTRAP/SIMULATED evidence. Directional contradictions apply a graded penalty and cap. Correlated members remain limited to one family vote.

This release does not alter Execution or enable LIVE trading.
