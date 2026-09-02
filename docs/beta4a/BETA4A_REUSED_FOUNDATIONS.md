# Beta 4A Reused Foundations

Beta 4A imports rather than reimplements:

- `PromotionRecommender.recommend()` for candidate recommendation.
- `CrossBundleDiagnosticsEngine` outputs as lower-layer truth.
- QG-05/QG-06/QG-07 temporal walk-forward, purge, embargo, and locked holdout principles.
- `FIRST_ELIGIBLE_PLAN` temporal eligibility invariant.
- Policy Identity and Extraction Identity.
- Immutable manifests, sealing, hashes, derived registries, and raw-metric/interpretation separation.

Beta 4A adds Feature Schema Identity but does not merge it into Policy or Extraction Identity.

Known compatibility dependency: Beta 3D-r3 adds `first_eligible_evaluation_timestamp` and `snapshot_timestamp` to lineage without changing Beta 3D behavior.
