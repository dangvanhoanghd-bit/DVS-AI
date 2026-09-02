# DVS AI Alpha 2.28.2 — Observation Quality & Coverage Audit

- Quality states: FULL / DEGRADED / BLOCKED.
- Readiness uses only bound, closed, finite, fresh observations with valid truth schema.
- Unbound, missing outcome, stale, invalid outcome and legacy truth rows remain available for pipeline diagnostics but are excluded from readiness evidence.
- Observe-only; MAIN immutable; LIVE disabled.
