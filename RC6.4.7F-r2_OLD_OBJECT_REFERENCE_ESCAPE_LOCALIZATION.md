# RC6.4.7F-r2 — Old Object Reference Escape Localization

This diagnostic-only release adds monotonically assigned CoinAnalysis tokens at
`Worker._execute_future` immediately after `scan_coin()` returns. The tracker
stores weak references, integer tokens, primitive metadata, and owner-path sets;
it never retains a strong reference to CoinAnalysis and validates every object-ID
lookup against `weakref() is obj` to prevent CPython address reuse aliasing.

Runtime evidence is written to:

`artifacts/runtime/coin_analysis_token_events.jsonl`

Instrumented direct owner transitions include `MainWindow.results`,
`MainWindow._scan_result_side_effect_queue`, `MainWindow._auto_paper_queue`, and
`FinalizationWorker.results`. Per-cycle survivor records are emitted as
`token_seen_after_cycle`, while weakref callbacks emit `token_collected`.

No memory retention policy or Decision Engine logic is changed.
