# DVS AI Beta 1A — Outcome Intelligence Foundation

## Added
- Immutable `candidate_feature_snapshots` table.
- Outcome maturity summary: pending, resolving, resolved, win/loss/invalid/ambiguous/expired, feature snapshots, learning-ready samples.
- Reproducible dataset builder using only resolved outcomes joined to immutable feature snapshots.
- JSONL and CSV export tools.
- Optional live feature snapshot capture through `EvaluationCapture.feature_snapshot`.

## Safety invariants
- Decision Engine unchanged.
- No threshold tuning.
- No MAIN/SHADOW promotion.
- No Quantum authority changes.
- No execution APIs.
