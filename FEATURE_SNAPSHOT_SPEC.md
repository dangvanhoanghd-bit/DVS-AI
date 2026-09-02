# Feature Snapshot Specification

## Core decision

Beta 3 does not create a third snapshot source. It builds on the existing immutable snapshot chain already required by Unified Outcome eligibility.

Canonical reference chain:

```text
UnifiedOutcomeRecord.feature_snapshot_hash
        ↓
existing candidate feature snapshot / evidence snapshot payload
        ↓
verified immutable bytes
        ↓
Feature Store materialization
```

## Required verification

Before feature extraction:

- `feature_snapshot_hash` is present;
- referenced snapshot exists;
- canonical SHA-256 recomputation matches;
- snapshot timestamp is at or before the governed decision/outcome boundary;
- source candidate/paper identities match the Unified record provenance;
- policy identity can be reconstructed or is explicitly stored.

## Historical policy

No historical backfill or reconstruction. Missing immutable snapshots remain:

`NOT_ELIGIBLE / HISTORICAL_SNAPSHOT_UNAVAILABLE`

Human review cannot override this requirement.

## Derived materialization

Beta 3 may create a derived, immutable feature row for research convenience, but that row is not a new source of truth. It must include the source `feature_snapshot_hash`, extraction schema version, extractor checksum, and full lineage. Any conflict is resolved in favor of the source snapshot bytes, not the derived row.
