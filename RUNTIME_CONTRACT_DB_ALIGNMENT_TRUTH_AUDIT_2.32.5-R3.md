# Truth Audit — Alpha 2.32.5-r3

- Quantum early/partial reports cannot crash UI or enable SHADOW apply.
- Missing validation keys are surfaced as SCHEMA_MISMATCH.
- Paper, Learning, Quantum and Shadow observation services share `data/dvs_paper_trades.db`.
- Store construction performs duplicate migration and unique-index creation before scanning starts.
- Diagnostics expose resolved DB path and idempotency schema state.
- Decision, Quantum optimization math, Promotion, Testnet and LIVE execution are unchanged.
