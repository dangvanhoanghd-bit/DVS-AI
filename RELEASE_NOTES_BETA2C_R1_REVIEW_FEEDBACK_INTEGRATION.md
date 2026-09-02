# Beta 2C-r1 — Review Feedback Integration

## Purpose

Closes the functional gap found by independent audit: review events were append-only evidence but were not applied to the governed UnifiedOutcome read model consumed by Learning, Quantum and Governance.

## Implemented

- Added `UnifiedReviewRepository` for read-only access to `unified_review_events`.
- Added SHA-256 validation for every review event.
- Added `UnifiedReviewResolver` and integrated it into `UnifiedOutcomeService.records()`.
- Latest valid review event wins; prior events remain immutable.
- `ACCEPT_CANDIDATE` and `ACCEPT_PAPER` select the corresponding source outcome.
- Snapshot remains mandatory. Manual acceptance cannot bypass `HISTORICAL_SNAPSHOT_UNAVAILABLE`.
- `EXCLUDE` produces `NOT_ELIGIBLE / EXCLUDED_BY_REVIEW`.
- Added governed provenance fields: `resolution_source`, `review_action`, `review_event_sha256`.
- Integrity Auditor now detects invalid hashes, orphan review targets, inconsistent decisions and unapplied review events.
- Release Gate blocks on review-feedback integrity failures.

## Safety boundaries preserved

- Decision Engine unchanged.
- No threshold modification.
- No automatic execution authority.
- Source outcome tables remain immutable.
- Soft fingerprint still never auto-merges.
- `TP1_HIT` remains non-terminal.
- Historical snapshots are never reconstructed.

## Verification

- Focused review-feedback tests: 9 passed.
- Full regression suite: 958 passed, 0 failed.
- `python -m compileall`: passed.
