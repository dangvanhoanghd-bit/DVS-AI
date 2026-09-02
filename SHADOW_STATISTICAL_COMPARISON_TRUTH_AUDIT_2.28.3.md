# DVS AI Alpha 2.28.3 — Shadow vs Baseline Statistical Comparison Audit

## Scope

- Paired MAIN/SHADOW observation comparison.
- Deterministic bootstrap confidence interval for expectancy delta.
- Minimum detectable improvement guardrail.
- Time-block stability check.
- Promotion Readiness integration.

## Truth boundary

Only quality-eligible, paired observations are accepted. The module is observe-only and cannot apply or promote configuration. MAIN remains immutable and LIVE execution remains disabled.

## Statistical interpretation

A positive point estimate is not enough. `BETTER` requires a positive confidence interval, an expectancy delta at least as large as the configured minimum detectable improvement, and sufficient stability across chronological blocks. If the interval crosses zero, the result is `INCONCLUSIVE`.
