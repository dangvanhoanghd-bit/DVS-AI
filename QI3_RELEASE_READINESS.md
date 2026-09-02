# QI-3 — Release Readiness & Production Qualification

QI-3 does not grant trading, Optimizer, or SHADOW authority. It provides a fail-closed qualification report for the governed research runtime.

## Qualification checks

1. Frozen `decision_engine.py` MD5 equals `72cf7d54e1ed6369400683358da8c0ef`.
2. `quantum_auto_apply_shadow` remains `false` and execution mode is PAPER/RESEARCH/SHADOW only.
3. QI-2 governance startup self-test passes under the configured allowlist and trusted bundle fingerprint.
4. The runtime JSONL audit ledger exists and its complete hash chain verifies from `GENESIS`.

Any failure produces `BLOCKED_NOT_QUALIFIED`. A passing result is named `QUALIFIED_RESEARCH_RUNTIME`; it is not permission to execute trades or automatically alter SHADOW.

## Command

```bash
python verify_quantum_release_qi3.py --project-root .
```

Exit code is `0` only when all checks pass and `2` otherwise. The self-hashed report is written to `data/quantum_release_qualification.json` by default.

## Operational rule

Production operators must provision the QI-2 environment variables externally. Test/dev governance bundles must never be placed in trusted production roots or added to the trusted fingerprint list.
