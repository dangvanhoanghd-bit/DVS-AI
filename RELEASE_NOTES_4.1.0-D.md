# DVS AI Alpha 4.1.0-D

## Statistical Reliability & Effective Sample Size

This release extends the read-only outcome analytics layer with:

- 15-minute market-event clustering using outcome time, with activation-time fallback.
- Kish-style temporal-cluster and symbol-concentration effective sample sizes.
- Conservative ESS equal to the minimum supported independence estimate.
- Deterministic cluster bootstrap 95% intervals for win rate and average realized R.
- Minimum-sample states: UNOBSERVABLE, INSUFFICIENT, EXPLORATORY, RELIABLE_DESCRIPTIVE.
- JSON and HTML disclosure of observed N, cluster count, ESS, confidence intervals, and limitations.

No score, threshold, gate, Decision Engine, trade plan, outcome resolution, or order authority was changed.
