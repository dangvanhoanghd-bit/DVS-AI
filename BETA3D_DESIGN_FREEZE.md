# Beta 3D — Cross-Bundle Comparative Diagnostics Design Freeze

Status: FROZEN

## Scope
Beta 3D verifies and compares multiple immutable Beta 3B bundles. It does not train, predict, infer, mutate bundles, access databases, or alter the Decision Engine.

## Comparison contexts
1. `SAME_POLICY_SAME_EXTRACTOR`: temporal comparison; raw metrics and descriptive shift labels permitted.
2. `SAME_POLICY_DIFFERENT_EXTRACTOR`: `EXTRACTOR_CONFOUNDED_CHANGE`; raw metrics only; not market drift.
3. `DIFFERENT_POLICY`: `CROSS_POLICY_CONTRAST`; raw metrics only; not evolution of one data line.

Policy Identity is `(policy_scope_id, policy_scope_hash, decision_engine_checksum)`. Extraction Identity is `(extractor_schema_version, extractor_checksum)`.

## Raw metrics and labels
Raw fields are `baseline_value`, `comparison_value`, `delta`, `absolute_change`, and `relative_change`. Interpretive labels are separate and use `STABLE`, `MINOR_SHIFT`, `MODERATE_SHIFT`, `MAJOR_SHIFT`. No inferential or statistical-significance language is permitted.

Diagnostic policy: `beta3d.cross_bundle.v1`.
Relative-change thresholds: 5%, 15%, 30%.

## Burn-in
The existing Beta 3 scale is reused unchanged. Any comparison below `RESEARCH_CANDIDATE_ONLY` remains raw-only and is marked `COMPARISON_UNOBSERVABLE` / `LOW_CONFIDENCE_COMPARISON`.

## Registry
The registry is a rebuildable in-memory index derived from `DatasetBundleVerifier`. Verified manifests and protected artifacts remain the sole source of truth. Staleness is recoverable by rebuild; verifier failure yields `BUNDLE_VERIFICATION_FAILED_EXCLUDED`.

## Timeline
The timeline contains only bundle data lineage using `parent_bundle_sha256`. It never mixes software milestones. It detects broken parent, cycle, duplicate identity, fork, cross-policy lineage, and extractor change points.

## Promotion
Hard constraints run before Pareto filtering. No weighted score exists.

Frozen lexicographic order:
1. burn-in level descending
2. coverage ratio descending
3. Beta 3B quality score descending
4. record count descending
5. verified manifest build timestamp descending
6. bundle SHA-256 ascending

When Type-A comparative evidence exists, the maximum label is `TRAINING_CANDIDATE`. When it does not exist, absolute fallback remains available but is capped at `ELIGIBLE_CANDIDATE`.
