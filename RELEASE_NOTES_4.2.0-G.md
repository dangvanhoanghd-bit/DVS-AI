# DVS AI Alpha 4.2.0-G

## Research Review, Annotation & Approval Workflow

- Separate `data/research_reviews.db` review ledger.
- Review targets: experiment, comparison, cohort, lineage report, cohort diagnostics.
- Append-only annotations and deterministic lifecycle: DRAFT → IN_REVIEW → APPROVED / REJECTED / CHANGES_REQUESTED.
- Target checksum verification detects research artifact drift.
- JSON/HTML review export.
- No experiment result mutation, no canonical database write, no Decision Engine invocation, no tuning.
