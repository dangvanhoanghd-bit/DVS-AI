# Dataset Versioning Specification

## Reused manifest pattern

Dataset versioning uses the project-proven canonical JSON and SHA-256 self-sealing pattern. No new versioning mechanism is introduced.

## Bundle layout

```text
dataset_<bundle_id>/
  training_dataset.jsonl
  exclusions.jsonl
  quality_report.json
  lineage_index.jsonl
  dataset.manifest.json
```

## Manifest required fields

- `manifest_schema_version`
- `dataset_schema_version`
- `bundle_id`
- `created_at_utc`
- `builder_version`
- `builder_checksum`
- `source_unified_service_version`
- `source_cutoff`
- `qualified_sample_count`
- `burn_in_state`
- `policy_scope_ids[]`
- `policy_scope_hashes[]`
- `feature_snapshot_hash_set_sha256`
- `dataset_file`
- `dataset_sha256`
- `exclusions_sha256`
- `quality_report_sha256`
- `lineage_index_sha256`
- `parent_bundle_id` (nullable)
- `change_reason`
- `self_sha256`

## Identity rule

`bundle_id` is content-addressed from canonical manifest fields excluding `self_sha256`, then prefixed with `LDS-`.

## Rollback

Rollback selects an earlier immutable bundle. It never mutates or overwrites a prior bundle. Parent-child relationships are explicit.
