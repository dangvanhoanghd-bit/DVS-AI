# Learning Data Lineage

## Required reverse trace

Every Training Dataset row must support this complete reverse path:

```text
dataset_row_id
  → dataset_bundle_id
  → feature_row_id(s)
  → unified_id
  → candidate_id / paper_trade_id
  → feature_snapshot_hash
  → source snapshot bytes
  → policy_scope_id / policy_scope_hash
  → decision_engine_checksum
```

## Lineage index schema

- `dataset_row_id`
- `dataset_bundle_id`
- `unified_id`
- `candidate_id`
- `paper_trade_id`
- `source_identity_type`
- `feature_snapshot_hash`
- `source_snapshot_location`
- `source_record_sha256`
- `feature_row_sha256s[]`
- `policy_scope_id`
- `policy_scope_hash`
- `decision_engine_checksum`
- `review_action`
- `review_event_sha256`
- `outcome_status`
- `lineage_sha256`

## Audit queries that must be answerable

1. Why is this row in the dataset?
2. Which exact source record and snapshot produced it?
3. Which policy/Decision Engine generation produced its features?
4. Was Human Review involved, and which event?
5. Which quality warnings or exclusions were applied?
6. Can the row be reproduced byte-for-byte?

## Referential integrity

A row with a missing lineage link is invalid and blocks publication. Lineage files are included in the self-sealed dataset bundle and covered by the manifest checksum.
