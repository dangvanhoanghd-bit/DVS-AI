# DVS AI Alpha 4.1.0-E

## Statistical Diagnostics Dashboard

Read-only GUI visibility for episode-level statistical reliability:

- reliability status and reason
- observed decisive episode count
- conservative effective sample size
- market-event cluster count and largest cluster
- cluster-size distribution
- clustered bootstrap 95% intervals
- candidate outcome funnel
- confidence calibration table
- explicit cross-symbol dependence and safety boundary

The dashboard reads the canonical paper database through OutcomeAnalyticsService on a background QThread. It has no write path to Decision Engine, configuration, thresholds, paper trades, or exchange orders.

Decision Engine and all source files under `dvs_ai/engines/` remain byte-for-byte unchanged from 4.1.0-D.
