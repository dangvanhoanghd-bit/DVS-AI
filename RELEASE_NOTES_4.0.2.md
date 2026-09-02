# DVS AI Alpha 4.0.2 — Indicator Inspector & Confidence Breakdown

## Added
- Rich read-only inspector metadata for every Decision Graph node.
- Node category and evidence source labels.
- Deterministic human-readable interpretation for CMF, RSI, OI, trend, liquidity, Wyckoff, risk, entry and authority evidence.
- Confidence Breakdown table beside the Decision Graph.
- Explicit total descriptive confidence row.

## Scientific constraints
- No indicator values are invented when they were not persisted.
- Confidence contribution remains descriptive and sums to the persisted confidence.
- No strategy re-execution, exchange call, authorization, promotion or authority transfer.
- Paper Authority remains LEGACY; Unified remains SHADOW_ONLY with quantity 0.
