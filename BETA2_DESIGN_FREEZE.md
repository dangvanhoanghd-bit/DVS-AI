# Beta 2 — Unified Outcome Pipeline — Design Freeze

Decision Engine, thresholds, execution authority and historical source rows remain unchanged.

## Frozen boundaries

- `QuantumDataAdapter` remains a read-only vocabulary convergence adapter and performs no cross-source deduplication.
- `CrossPipelineMonitor` remains observe-only. Only `EXPLICIT_CROSS_SOURCE_LINK` may authorize automatic merge.
- Soft fingerprints produce `AMBIGUOUS_MATCH / MANUAL_REVIEW_REQUIRED`; they never produce Learning or Quantum samples automatically.
- `TP1_HIT` is intermediate, never terminal.
- Terminal states: `WIN`, `LOSS`, `INVALID`, `AMBIGUOUS`, `EXPIRED`.
- Eligibility requires terminal outcome + immutable snapshot + explicit/manually approved identity + no unresolved conflict + integrity pass.
- Historical candidates without snapshots remain permanently `NOT_ELIGIBLE / HISTORICAL_SNAPSHOT_UNAVAILABLE`; no backfill is permitted.
- Terminal disagreement is `CONFLICT`; no source is silently preferred. Human review may accept paper, accept candidate, or exclude, with reviewer/reason/evidence recorded.
- Legacy direct reads follow `Deprecate -> Audit -> Remove`.

## Beta 2A implementation boundary

This release introduces `UnifiedOutcomeRecord`, `UnifiedOutcomeBuilder`, and `UnifiedOutcomeService`, plus behavioral attack tests. Consumer migration is deliberately staged and is not claimed complete until Learning, Quantum and Governance all report the same eligible count and legacy-read telemetry reaches zero.
