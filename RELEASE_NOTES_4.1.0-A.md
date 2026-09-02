# DVS AI Alpha 4.1.0-A

## Back to Basics — Outcome Infrastructure Recovery

Implemented without changing Decision Engine scoring, thresholds, gates, or timeframe weights.

### Added
- Canonical deterministic decision/trade-plan profile hashing with normalized floats.
- Setup Episode / Evaluation separation to prevent pseudo-replication.
- Structural zone fingerprinting using 0.5 ATR buckets.
- Spring/Upthrust event identity by event type, timeframe, and trigger-candle timestamp.
- FIRST_ELIGIBLE_PLAN candidate activation policy.
- 8 x 15m bar entry expiry policy (120 minutes), frozen in trade-plan profile hash.
- Census, isolated-rejection, and compound-rejection cohorts.
- Canonical schema in `dvs_paper_trades.db` for episodes, candidates, gates, outcomes, traces, runs, and failures.
- Outcome Resolution Coordinator with one persistent QThread and coalesced requests.
- Automatic resolution on application startup and every 60 seconds.
- Structured resolution run/failure journals.
- Explicit cross-symbol dependence metadata foundation.

### Preserved
- Existing `OutcomeTracker` 1m candle resolution logic.
- Existing `PaperTradeService` resolution logic.
- Existing `scan_signals`, `paper_trades`, `shadow_observations`, and qualification authority roles.
- Shadow-only / paper authority safety boundary.

### Verification
- 694 tests passed.
- Python compileall passed.
