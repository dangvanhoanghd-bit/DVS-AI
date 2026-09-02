# Release Notes — Beta 3 Design Freeze

## Status

Adaptive Learning Foundation design frozen. No production learning code or model training was introduced.

## Key frozen decisions

- Reuse QBP burn-in thresholds 30/100/300/500.
- Below 30 qualified samples returns `UNOBSERVABLE`; no misleading empty dataset artifact.
- Existing `feature_snapshot_hash` remains the immutable source reference; no third snapshot truth.
- Reuse QG-13 policy scope identity, including Decision Engine checksum and governed interacting parameters.
- Human Review is conditional, not mandatory for explicit automatic merges; existing review must be valid.
- Reuse QBP-3 Holm-Bonferroni and deterministic bootstrap controls for insights.
- All insights include sample size, confidence interval, policy scope, and cautious association vocabulary.
- Reuse self-sealing SHA-256 manifest pattern.
- Added full row-level lineage specification.
- Safety Layer remains separate and fail-closed.

## Next authorized step

Write Beta 3 attack-test specifications first, then implement only the Learning Candidate Builder, feature projection, manifest builder, and safety checks in small audited increments.
