# Beta 4A Feature Matrix Builder RC1 — Release Notes

Status: **AUDIT_CANDIDATE**

This release implements Beta 4A M2 on top of the M4 Leakage Detector RC1 repository.

Implemented:

- immutable ordered Feature Schema Manifest;
- Feature Schema Identity including frozen categorical vocabularies;
- deterministic Train/Validation/Test matrices;
- no encoder fitting and no implicit imputation;
- missing-row and missing-feature exclusion records;
- strict hard-block option for incomplete schema;
- unknown-category exclusion;
- identity linkage to Split Artifact, bundle, and Leakage Report;
- canonical SHA-256 matrix sealing;
- stable `feature_schema.manifest.json` writer.

This release does not train or evaluate an ML model and does not alter Beta 3 decision, promotion, registry, quality, or lineage behavior.
