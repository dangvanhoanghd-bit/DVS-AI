# DVS AI Alpha 4.3.0D-2 — Historical Ablation Engine

## Added
- Read-only `HistoricalAblationEngine`.
- Immutable `AblationStudy`, `OutcomeSummary`, and sealed result manifests.
- FIRST_ELIGIBLE_PLAN replay gate inherited from 4.3.0D-1.
- Independent bundle verifier.

## Scientific boundary
This release performs leave-one-evidence-out **observability projection only**.
It does not re-execute the frozen Decision Engine and therefore reports
`COMPLETED_NON_IDENTIFIABLE`, never a causal or performance counterfactual.
Recorded TradePlan and outcomes remain unchanged.

## Authority
Optimizer, recommendation, SHADOW write, MAIN write, and order authority remain disabled.
