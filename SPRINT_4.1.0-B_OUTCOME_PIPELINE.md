# DVS AI Alpha 4.1.0-B — Outcome Pipeline

- Decision Engine remains frozen and byte-identical to 4.1.0-A.
- Added CandidateOutcomeResolver using 1m candles.
- Added transactional PENDING -> RESOLVING claims.
- Added 15-minute stale-claim recovery.
- Added WAITING_ENTRY -> ACTIVE -> WIN/LOSS/AMBIGUOUS/EXPIRED_UNFILLED lifecycle.
- Invalidation before entry is EXPIRED_UNFILLED, never LOSS.
- Added per-candidate failure journaling and idempotent terminal updates.
- Integrated candidate resolution into the existing persistent OutcomeResolutionCoordinator.
- Added Cross-Symbol Dependence limitation to Scientific Report JSON/HTML.
- 698 tests pass.
