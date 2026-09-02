# Audit — DVS AI Alpha 4.3.0D-3

- Decision Engine source is not imported or executed by the uncertainty estimator.
- FIRST_ELIGIBLE_PLAN replay verification is mandatory.
- Outcome/future fields cannot be selected as evidence targets.
- Effective sample size cannot be bypassed by raw row count.
- Bootstrap is cluster-aware and deterministic under a recorded seed.
- Causal claims are explicitly forbidden in the manifest.
- Optimizer, recommendation, SHADOW, MAIN and order authority flags are always false.
- Exported artifacts are independently checksum-verifiable.
