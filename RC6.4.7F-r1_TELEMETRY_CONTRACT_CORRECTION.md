# RC6.4.7F-r1 — Telemetry Contract Correction

- Decision Engine unchanged.
- `scan_results` uses no false bounded limit and records exact container replacement.
- `_scan_result_side_effect_queue` and `_auto_paper_queue` are named literally and measured at append/pop/clear/extend mutation sites.
- `peak_current` is updated immediately after enqueue and before later dequeue work.
- `LearningService._snapshot_cache` emits exact replacement events for database refresh and explicit invalidation.
- Direct CoinAnalysis owners `MainWindow.results`, `_stream_table_pending`, and `current_analysis` are exposed without claiming a fictitious CoinAnalysis graph.
- No memory retention policy is changed; this is telemetry-only localization.
