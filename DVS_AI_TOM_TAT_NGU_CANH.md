
## Beta 2 Design Freeze — Unified Outcome Pipeline
Outcome intermediate: PENDING, TRACKING, TP1_HIT. Terminal: WIN, LOSS, INVALID, AMBIGUOUS, EXPIRED. Unified states: UNMATCHED, AMBIGUOUS_MATCH, CONFLICT, MANUAL_REVIEW_REQUIRED, NOT_ELIGIBLE, UNIFIED_ELIGIBLE, LEARNING_READY, RESOLVED_EXCLUDE. Dedup is not performed inside QuantumDataAdapter. Automatic merge requires EXPLICIT_CROSS_SOURCE_LINK; soft fingerprint is review-only. Historical missing snapshots remain permanently NOT_ELIGIBLE with no backfill. Legacy reads use Deprecate -> Audit -> Remove.

## Beta 2B — Consumer Migration

Default consumers now use `UnifiedOutcomeService`:

- Learning Dashboard / `LearningService`
- Quantum Optimizer
- Quantum Readiness

`QuantumDataAdapter` keeps its original no-dedup contract. Deduplication and eligibility remain above the adapter in `UnifiedOutcomeBuilder`.

Only explicit cross-source identities may be merged automatically. Soft fingerprints remain `AMBIGUOUS_MATCH` / manual-review only.

Legacy pre-unified database access is schema-gated and emits `LEGACY_SQL_PATH_USED`. It is not used when the complete unified pipeline schema is available.

## Beta 2C — Unified Integrity & Operational Readiness

- UnifiedOutcomeService remains the governed read model for Learning, Quantum and Governance.
- UnifiedIntegrityAuditor is read-only and checks duplicates, snapshot eligibility, terminal state integrity, unresolved conflict and ambiguous match queues.
- UnifiedReviewLedger is append-only. Human review may record ACCEPT_PAPER, ACCEPT_CANDIDATE or EXCLUDE, with reviewer, reason, evidence and checksum. Historical source rows are never rewritten.
- Historical terminal candidates without immutable snapshots remain permanently NOT_ELIGIBLE / HISTORICAL_SNAPSHOT_UNAVAILABLE.
- TP1_HIT remains non-terminal and cannot become Unified Eligible or Learning Ready.
- UnifiedReleaseGate blocks a release when critical/error integrity findings exist, duplicate identities exist, or LEGACY_SQL_PATH_USED telemetry is non-zero.
- This layer has observation and release-governance authority only. It has no Decision Engine, threshold, MAIN/SHADOW or execution authority.

## Beta 2C-r1 — Review Feedback Integration

Independent audit found that manual review events were recorded but not consumed by UnifiedOutcomeService. Beta 2C-r1 closes that gap by validating and applying the latest valid ledger event to the governed read model. Manual review can resolve a conflict but cannot bypass terminal-outcome, immutable-snapshot or integrity requirements. Learning, Quantum and Governance therefore receive the same reviewed state from the same source of truth.
