# Release Notes — Beta 3D-r2 Quality Truth Fix

Beta 3D-r2 fixes the independent-audit finding that registry quality metrics
were being recomputed instead of inherited from Beta 3B.

Changed:

- Registry `coverage_ratio` now equals Beta 3B `quality_report.json.coverage`.
- Registry `beta3b_quality_score` now equals Beta 3B
  `quality_report.json.quality_score`.
- Removed the feature-only derived quality formula and unsupported `PARTIAL`
  vocabulary from Beta 3D.
- Added defensive exclusion for missing, invalid, non-finite, or out-of-range
  quality-report metrics.
- Added two real-bundle attack/regression tests.

Decision Engine and all files under the trading engine contract remain unchanged.
