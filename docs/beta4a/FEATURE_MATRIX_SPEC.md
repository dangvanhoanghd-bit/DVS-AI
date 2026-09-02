# Beta 4A M2 — Feature Matrix Builder Specification

## Frozen purpose

M2 converts already-approved dataset rows into deterministic numeric matrices. It consumes the M3 Split Artifact and a passing M4 Leakage Detection Report. It never recomputes indicators, labels, quality, coverage, burn-in, lineage, or temporal eligibility.

## Immutable schema

`feature_schema.manifest.json` is the ordered ML contract. Each column records:

- `name`
- `dtype`
- `encoding`
- `column_index`
- frozen `categories` when categorical

`FeatureSchemaIdentity` is independent of Policy Identity and Extraction Identity. Its ordered-feature hash includes the column order, data type, encoding, and categorical vocabulary/order.

## Deterministic build

For identical rows, schema, Split Artifact, Leakage Report, and bundle identity, repeated builds must produce identical:

- partition row order
- column order
- encoded values
- labels
- exclusions
- matrix SHA-256

Input dictionary order and input row iteration order are not schema contracts. M2 always follows Split Artifact row order and schema `column_index` order.

## Encoding

Encoders are frozen in the schema and are never fitted from Train rows.

- `numeric` / `identity`: finite numeric values only
- `boolean`: `False -> 0`, `True -> 1`
- `categorical`: zero-based index in the frozen category tuple

Unknown categories never create columns and produce `UNSEEN_CATEGORICAL_VALUE`, excluding the affected row.

## Missing data

No implicit imputation is permitted.

Default behavior:

- `ROW_EXCLUDED_INCOMPLETE_SCHEMA`

Explicit strict behavior:

- `FEATURE_SCHEMA_MISMATCH` hard block

## Gates

M2 refuses to build when:

- the M4 report is blocked;
- split/report/bundle identities disagree;
- the M4 feature-schema identity differs from M2 schema identity;
- a requested external column order differs from the frozen schema.

Frozen status codes:

- `FEATURE_SCHEMA_MISMATCH`
- `COLUMN_ORDER_MISMATCH`
- `ROW_EXCLUDED_INCOMPLETE_SCHEMA`
- `UNSEEN_CATEGORICAL_VALUE`
- `LEAKAGE_REPORT_HARD_BLOCKED`
