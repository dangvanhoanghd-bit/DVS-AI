# Beta 4A RC4.1 Immutable Capture Identity Runtime Hotfix

- Replaced mutation of frozen CoinAnalysis with immutable UnifiedCaptureIdentity.
- LiveEpisodeCaptureRunner now transports identity as a separate signal payload.
- MainWindow retains per-analysis identity until Auto Paper consumes it.
- PaperTradeService.auto_consider accepts explicit unified_identity and remains fail-closed.
- Research Cohort shutdown uses shutdown(timeout_ms) when available.
- LearningService caches a consistent read snapshot for five seconds to avoid repeated full Unified Outcome scans during one UI refresh.
- Decision Engine unchanged.
