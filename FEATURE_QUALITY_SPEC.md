# Feature Quality Specification

## States

- `VALID`
- `WARNING`
- `INVALID`

## Invalid conditions

- missing source snapshot;
- snapshot hash mismatch;
- non-finite numeric value;
- timestamp leakage;
- unknown unit where unit is required;
- policy identity missing or inconsistent;
- extractor checksum missing;
- duplicate/conflicting feature value for the same feature row identity;
- unsupported feature schema.

## Warning conditions

- optional feature missing;
- stale but still pre-decision observation;
- low source quality explicitly recorded;
- sparse cohort coverage;
- value outside historical descriptive range but not impossible.

## Aggregation

A Learning Candidate is invalid if any mandatory feature is `INVALID`. Warnings do not automatically exclude a candidate but must be counted and surfaced in the dataset quality report.

## No silent imputation

Beta 3 does not impute missing values unless a future design freeze explicitly defines a deterministic, audited imputation policy. Missing remains missing and is reported.
