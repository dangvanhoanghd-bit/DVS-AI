# Beta 3D-r2 Quality Truth Fix — Audit Report

## Finding

Beta 3D-r1 populated `RegistryEntry.coverage_ratio` and
`RegistryEntry.beta3b_quality_score` by recomputing feature-only metrics from
released dataset rows. That calculation ignored Beta 3B exclusions and included
an unsupported `PARTIAL` quality label. It therefore created a competing quality
source and could mis-rank promotion candidates.

## Fix

`BundleRegistry._derive_metrics()` now reads the sealed Beta 3B values directly
from `quality_report.json`:

- `coverage`
- `quality_score`

No quality metric is recomputed in Beta 3D. Invalid, non-finite, or out-of-range
quality metrics cause the bundle to be excluded from the derived registry with a
specific quality-report error code.

## Independent regression tests added

`tests/test_beta3d_quality_truth_audit.py`

1. A real Beta 3B bundle with 30 qualified rows and 10 exclusions reports
   `coverage=0.75` and `quality_score=0.75`; the Beta 3D registry now carries both
   values exactly.
2. Two real 100-row bundles in the same Type-A cohort, one clean and one with 25
   exclusions, produce registry quality values `1.0` and `0.8`. Promotion selects
   the clean bundle as the sole `TRAINING_CANDIDATE`.

## Verification

- Beta 3D focused + attack + quality-truth tests: 68 passed, 0 failed.
- Full project regression: 1120 passed, 0 failed.
- Python compileall: PASS.
- Decision Engine MD5: `72cf7d54e1ed6369400683358da8c0ef`.
- Decision Engine SHA-256: `00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce`.
