# DVS AI Alpha 4.1.0-G

## Episode Data Quality & Integrity Monitor

Read-only integrity diagnostics for the canonical episode/candidate/outcome infrastructure.

Checks:
- missing and orphan diagnostic traces
- orphan evaluations, candidates, and outcomes
- duplicate activation and activation-link mismatch
- episode/candidate/trace profile hash mismatch
- evaluation sequence gaps and evaluation-count mismatch
- open episodes stale for more than 2 hours
- WAITING_ENTRY candidates past entry expiry
- RESOLVING outcome claims stale for more than 30 minutes

Scientific boundary:
- no data repair
- no record mutation
- no threshold or score tuning
- no Decision Engine changes
- no exchange-order capability

Verification:
- 717 tests passed
- compileall passed
- headless widget smoke test passed
- 27/27 engine Python files unchanged
- decision_engine.py MD5: 72cf7d54e1ed6369400683358da8c0ef
