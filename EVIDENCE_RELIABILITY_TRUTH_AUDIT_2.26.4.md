# DVS AI Alpha 2.26.4 — Evidence Reliability Truth Audit

## Verified scope
- PAPER trades now persist an explicit evidence-family snapshot at signal creation.
- Legacy rows without snapshots are excluded; reasoning text is never reverse-engineered.
- Reliability is estimated per evidence family with exponential time decay.
- Symbol/regime estimates use hierarchical Bayesian shrinkage toward regime/global priors.
- Insufficient effective sample size returns `UNKNOWN`, never 0% or 100%.
- The feature is observe-only and does not alter Evidence Fusion, confidence, thresholds, sizing, or Execution.

## Families
`TIMING`, `ENTRY`, `ORDER_FLOW`, `DIRECTION`, `MARKET`.

## Limitations
- Reliability is based only on newly recorded PAPER trades with snapshots.
- It is not causal feature attribution.
- It does not yet weight Evidence Fusion; that requires a separate audit.
- LIVE execution remains disabled.
