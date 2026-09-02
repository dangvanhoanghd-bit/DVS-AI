# DVS AI Alpha 4.2.1 — Audit Hardening Report

Baseline: **DVS AI Alpha 4.2.0-L** (preserved unchanged as the audited reference release).

## Changes

1. `OutcomeAnalyticsService` now opens the paper database with SQLite URI `mode=ro` and `PRAGMA query_only=ON` for analytics queries.
2. Independent Audit Bundle Verification now supports Normal and Strict modes. Strict mode fails on archive members absent from the manifest.
3. Review integrity results now state an explicit integrity level and verification basis. Database-backed targets are Level 2, independently resolved from the read-only workspace. Report-like targets are Level 1 and no longer receive a tautological PASS.
4. Audit bundle manifests include audit-assurance metadata.
5. Added `audit_register.json` and `KNOWN_DESIGN_LIMITATIONS.md`.

## Explicit non-changes

- No Decision Engine source changes.
- No statistical formula changes.
- No review workflow transition changes.
- No incident lifecycle changes.
- No alert threshold changes.
- No execution authority changes.
- No tuning or heuristic optimization.
