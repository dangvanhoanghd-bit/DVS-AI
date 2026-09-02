# DVS AI Beta 2C — Unified Integrity & Operational Readiness

## Scope

Beta 2C adds a read-only integrity and release-governance layer above `UnifiedOutcomeService`.
It does not modify the frozen Decision Engine, thresholds, execution authority, MAIN/SHADOW semantics, or historical source records.

## Added

- `UnifiedIntegrityAuditor`
  - duplicate unified ID detection
  - duplicate source identity detection
  - eligible-without-snapshot detection
  - non-terminal eligibility detection
  - unresolved conflict and ambiguous-match reporting
  - deterministic report checksum
- `UnifiedReviewLedger`
  - append-only manual review events
  - ACCEPT_PAPER / ACCEPT_CANDIDATE / EXCLUDE actions
  - reviewer, reason, evidence and event checksum
  - no mutation of source outcome tables
- `UnifiedReleaseGate`
  - blocks on integrity CRITICAL/ERROR findings
  - blocks on duplicate identity conditions
  - blocks when legacy SQL telemetry is non-zero
  - observation/release-governance authority only

## Historical snapshot policy

Historical terminal records without immutable snapshots remain `NOT_ELIGIBLE` with reason
`HISTORICAL_SNAPSHOT_UNAVAILABLE`. No retrospective snapshot synthesis is performed.

## Manual review policy

Conflict and ambiguous records remain blocked until a human review event is recorded.
The ledger records the decision but does not rewrite historical source rows.
