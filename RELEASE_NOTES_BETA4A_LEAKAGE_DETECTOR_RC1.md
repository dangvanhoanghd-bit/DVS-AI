# Release Notes — Beta 4A M4 Leakage Detector RC1

This audit candidate adds the first production implementation of Beta 4A M4.

Added:

- `dvs_ai/beta4a/leakage_detector.py`
- deterministic `LeakageDetectionReport`
- temporal lineage consistency verification
- structural-group split verification
- cross-bundle duplicate identity defense-in-depth
- warning-only suspicious label correlation diagnostics
- `LeakageDetector.require_pass()` downstream gate
- focused M4 tests
- expanded M4 specification

No Beta 3 decision, promotion, registry, quality, burn-in or feature-generation
logic was changed.
