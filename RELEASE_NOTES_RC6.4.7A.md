# RC6.4.7A — Watchdog, GC and Callback Diagnostics

## Frozen boundaries
- Decision Engine unchanged.
- RC6.4.6C generation-token cleanup unchanged.
- Paper-only execution safety unchanged.

## Patch 1 — Auto Paper watchdog authority
- Adds `_rc647_capture_submitted_keys` as the explicit submission authority.
- Auto Paper delayed tracking is armed only for keys that actually reached `identity_capture_submitted`.
- Non-submitted scan results emit `auto_paper_watchdog_not_armed_no_capture_submission` and never produce a 30-second delayed warning.
- A second fail-closed guard suppresses any non-submitted key that reaches the batch processor.

## Patch 2 — GC and allocator evidence
- Registers `gc.callbacks` and writes `gc_events.jsonl` for generation 0/1/2 collection start/stop events.
- Records `sys.getallocatedblocks()`, `gc.get_count()`, active GUI callback, queue size and identity-map size.
- Adds per-`auto_paper_batch` allocator samples in `allocator_samples.jsonl`.

## Patch 3 — Cross-thread active callback monitor
- Adds a dedicated daemon monitor thread sampling the shared callback context every 250 ms.
- Long-running callbacks (>=100 ms) are recorded while still active in `active_callback_samples.jsonl`.
- This avoids the structural limitation of a scheduler probe running on the blocked GUI event loop.

## Patch 4 — Collection snapshot writer verification
- Writes `collection_snapshot_writer_started` into `collection_snapshots.jsonl` at startup.
- Keeps the 20-second collection snapshots and adds submission-set size, allocated blocks and GC counters.
- Writes `collection_snapshot_writer_stopped` during normal shutdown.

## Verification
- Python compilation: PASS.
- Focused lifecycle/UI tests: 17 PASS.
