# QBP-1 Real Burn-in Infrastructure

## Implemented scope

- Deterministic quality eligibility filter over `UnifiedOutcome`.
- Per-record eligibility decisions, exclusion reasons, provenance-preserving hashes, and dataset digest.
- Observe-only cross-pipeline overlap monitor. It reports explicit links and soft fingerprints but never merges or deletes records.
- Append-only hash-chained milestone ledger for 30/100/300/500 qualified outcomes.
- Dashboard snapshot model for progress, locks, exclusions, source counts, and overlap warnings.
- QBP-1 coordinator and verifier CLI.

## Audit clarifications from RC1

- `INVALID` in the legacy tracker means `STOP_BEFORE_TP1` after an active/filled trade with realized-R -1.0. It therefore remains LOSS under rule `LEGACY_INVALID_TO_LOSS_V1`.
- `PARTIAL_STOP` is the single documented exception to the no-PnL-inference rule: legacy vocabulary does not carry the net sign, so finite realized-R is used under isolated rule `LEGACY_PARTIAL_STOP_R_SIGN_V1`.
- Cross-source soft matches are warnings only. No heuristic deduplication is performed.

## Safety boundary

This release does not grant optimizer, recommendation, SHADOW, MAIN, production, or trade-execution authority. Milestone ledger entries hard-code all authority fields to false.

## Not claimed

- No claim of 30 real qualified outcomes.
- No ESS, walk-forward, purge/embargo, bootstrap, stability, or multiple-comparison result on real data.
- No Paper Authority Handover.
