# DVS AI Alpha 2.28.2 — Observation Quality & Coverage Audit Truth Audit

## Verified scope
- MAIN and SHADOW eligibility are evaluated on the same `CoinAnalysis` in `PaperTradeService.auto_consider()`.
- One append-only observation is recorded before any PAPER trade is created.
- When a PAPER trade is created, the observation is bound to the exact `paper_trade_id`.
- CLOSED/EXPIRED outcomes are linked by `paper_trade_id`, not by symbol or timestamp heuristics.
- Outcome writes are idempotent and cannot overwrite a previously closed observation.
- Truth Dashboard shows runtime counters: recorded, bound, closed, errors, active candidate.

## Safety boundary
- Observe/PAPER-only.
- No order API, TradeIntent, PositionSizer or live execution dependency.
- MAIN remains immutable and LIVE remains disabled.

## Known limitation
An observation without a corresponding PAPER trade remains open and has no counterfactual outcome. The runtime does not invent an outcome for decisions that were not traded.
