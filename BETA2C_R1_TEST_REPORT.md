# Beta 2C-r1 Test Report

## Review-feedback attack scenarios

1. ACCEPT_CANDIDATE + terminal + immutable snapshot -> UNIFIED_ELIGIBLE.
2. ACCEPT_CANDIDATE without snapshot -> NOT_ELIGIBLE / HISTORICAL_SNAPSHOT_UNAVAILABLE.
3. ACCEPT_PAPER resolves conflict using Paper outcome.
4. EXCLUDE -> NOT_ELIGIBLE / EXCLUDED_BY_REVIEW.
5. Latest valid event wins while ledger remains append-only.
6. Tampered event SHA-256 is rejected and reported.
7. Valid event targeting a missing unified record is reported.
8. Integrity Auditor and Release Gate block invalid review state.
9. UnifiedOutcomeService exposes the reviewed state consistently through records(), eligible(), learning_ready() and statistics().

## Results

- Focused suite: 9 passed.
- Complete project suite: 958 passed.
- Failures: 0.
