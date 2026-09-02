# DVS AI Alpha 4.2.0-C — Experiment Result Comparison & Reproducibility Verification

- Compare two or more completed experiment runs.
- Verify snapshot, analysis, parameters, frozen engine MD5, and result SHA-256.
- Deterministic verdicts: REPRODUCIBLE, DATASET_DRIFT, PARAMETER_DRIFT, ANALYSIS_DRIFT, ENVIRONMENT_DRIFT, RESULT_DIVERGENCE, INCOMPLETE_RUN_SET.
- Persist immutable comparison reports in the isolated research workspace.
- Export JSON and HTML audit reports.
- Read-only toward canonical data; no tuning and no Decision Engine invocation.
