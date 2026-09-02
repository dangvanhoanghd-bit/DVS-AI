# Milestone 1.2 — Audit Notes

## Preserved boundaries

- Bridge remains read-only.
- Bridge continues to use JSON files only.
- No scientific engine Python package is imported.
- No execution, exchange, database, deployment, TESTNET, or LIVE behavior is enabled.
- Safety checks remain independent Boolean gates; no weighted or composite score exists.

## Intentional policy

A packaged snapshot fallback is classified as `DEGRADED`, not `VERIFIED`, because the displayed source is not the backend root selected by the operator. The snapshot may still contain safe artifacts, but source provenance is part of operational truth.

## Remaining limitation

This release validates the Python code and automated GUI regression suite. A native Windows/PySide6 visual smoke test should still be performed on the target workstation before moving to Milestone 2.
