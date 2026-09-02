# DVS AI Alpha 2.28.0 — Evidence Validation Truth Audit

## Verified scope
- Candidate vs current SHADOW comparison from the same chronological backtest report.
- Append-only paired Baseline/SHADOW observation store.
- Observe-only promotion readiness states.
- Pending candidate and promotion timeline panel in Truth Dashboard.

## Safety boundary
No Decision, sizing, TradeIntent, order routing, MAIN mutation, auto-promotion, Testnet, or LIVE integration.

## Limitations
- Observation outcomes accumulate only after this release is deployed.
- Counterfactual comparison is limited to recorded paired decisions/outcomes.
- `READY_FOR_NEXT_REVIEW` is not permission to apply MAIN or enable execution.
