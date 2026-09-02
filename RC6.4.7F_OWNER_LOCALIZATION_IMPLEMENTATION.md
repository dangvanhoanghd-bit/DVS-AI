# RC6.4.7F — Owner Localization Counters

## Scope

This release adds lightweight, direct-owner telemetry for six runtime owner families while keeping full heap census disabled and leaving the frozen Decision Engine unchanged.

Telemetry output: `artifacts/runtime/retention_owner_counters.jsonl`.

## Direct owner paths

1. `MainWindow.results` — scan result objects.
2. `MainWindow._scan_result_side_effect_queue` — transient CoinAnalysis graph queue.
3. `MainWindow._auto_paper_queue` — in-memory decision candidate queue.
4. `MainWindow._capture_identity_by_key` — unified identity map.
5. `MainWindow.learning_service._snapshot_cache` — learning observation snapshot cache.
6. `MainWindow.service._frame_cache` — bounded scanner frame/history cache.

Each record contains owner and container instance IDs, baseline/current count, added/released/evicted totals, accounting delta, bounded limit, cycle index, and nearest-process RSS.

## Safety properties

- No `gc.get_objects()`.
- No domain object serialization or `repr()`.
- Only integer `id()` values are retained for cross-cycle set differences.
- At most one owner snapshot set per finalization cycle.
- Local release detection uses immediate before/after counts at the mutation site for `MainWindow.results` replacement.
- Full object census remains default-off.
- Decision Engine is unchanged.
