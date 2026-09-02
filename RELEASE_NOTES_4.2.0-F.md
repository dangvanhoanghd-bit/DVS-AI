# DVS AI Alpha 4.2.0-F

## Research Dataset Lineage & Provenance Explorer

- Read-only graph model for snapshot → experiment → comparison/cohort relationships.
- Detects orphan references, frozen-engine MD5 mismatches, duplicated source snapshots, branch points, unused snapshots and repeated result checksums.
- Adds `Lineage & Provenance` under the Research sidebar group.
- Exports JSON and HTML audit reports.
- No Decision Engine invocation, no tuning, no canonical/workspace writes.
