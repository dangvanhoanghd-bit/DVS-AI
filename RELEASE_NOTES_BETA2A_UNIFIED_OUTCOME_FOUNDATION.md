# Beta 2A — Unified Outcome Foundation

Implemented the governed read model above the existing convergence adapter.

- Added `UnifiedOutcomeRecord`, `UnifiedOutcomeBuilder`, and `UnifiedOutcomeService`.
- Preserved the no-dedup contract of `QuantumDataAdapter`.
- Reused `CrossPipelineMonitor` as the sole match detector.
- Only explicit cross-source links may auto-merge.
- Soft fingerprints are manual-review-only.
- Terminal disagreements produce `CONFLICT`; neither source is silently preferred.
- Immutable snapshot is mandatory for eligibility.
- Historical missing snapshots remain permanently not eligible; no backfill.
- Added five behavioral attack tests.

This is the Beta 2A foundation. Learning, Quantum and Governance consumer migration remains staged for Beta 2B; no claim of completed convergence is made in this release.
