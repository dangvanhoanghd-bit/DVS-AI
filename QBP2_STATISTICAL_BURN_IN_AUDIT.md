# QBP-2 Statistical Burn-in RC1

Implemented as observe-only research infrastructure:

- QBP-2A Outcome Qualification Engine: QUALIFIED / REJECTED / PENDING_REVIEW.
- QBP-2B conservative AR(1) Effective Sample Size diagnostic.
- QBP-2C chronological walk-forward fold builder with explicit purge and embargo sets.
- QBP-2D dataset integrity audit by source, symbol, direction, regime, and outcome.
- QBP-2E statistical readiness report and capability locks.

Safety invariants:

- No Decision Engine changes.
- No optimizer, MAIN, SHADOW-write, recommendation, or execution authority.
- `authority_granted` and `production_or_execution_authority` are always false.
- ESS / walk-forward / purge-embargo research capabilities require at least 100 qualified outcomes.
