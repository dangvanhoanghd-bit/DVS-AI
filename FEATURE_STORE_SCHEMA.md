# Feature Store Schema

## Storage principle

The Feature Store is an immutable research projection, not an operational truth database. It must be exportable as canonical JSONL/Parquet-like rows with a self-sealed manifest. SQLite may be used as a transport/cache only if rows remain content-addressed and rebuildable from source truth.

## Feature row schema

Required fields:

- `feature_row_id`
- `unified_id`
- `candidate_id`
- `paper_trade_id` (nullable)
- `feature_snapshot_hash`
- `snapshot_timestamp`
- `feature_name`
- `feature_type`
- `feature_value`
- `feature_unit` (nullable)
- `feature_source_path`
- `feature_quality`
- `quality_reasons[]`
- `extractor_schema_version`
- `extractor_checksum`
- `decision_engine_checksum`
- `policy_scope_id`
- `policy_scope_hash`
- `trade_plan_profile_hash` where applicable
- `outcome_status`
- `realized_r` (nullable)
- `review_action` (nullable)
- `review_event_sha256` (nullable)
- `source_record_sha256`
- `row_sha256`

## Policy identity — QG-13 reuse

`policy_scope_hash` is computed with the existing canonical policy-scope concept:

- includes `decision_engine_checksum`;
- includes governed interacting parameters relevant to feature/decision semantics;
- excludes operational settings such as UI, logging, watchlist, and worker counts;
- uses the same canonical JSON/hash semantics as the Quantum dataset factory.

Features from different policy scope hashes must not be silently pooled. Dataset manifests must either select one policy scope or declare explicit stratification by scope.

## Version terminology

- `extractor_schema_version`: shape/meaning of extraction code;
- `policy_scope_id/hash`: semantic generation policy;
- `dataset_schema_version`: dataset row contract;
- `bundle_version`: immutable export identity.

The generic word `version` must not be used without one of these qualifiers.
