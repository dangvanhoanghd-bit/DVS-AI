# Sprint A2 V2 — GUI Performance Candidate

## Source status
SOURCE VERIFIED candidate; runtime effectiveness remains pending.

## Implementation
- `HistoryPrepareWorker`: opens SQLite inside `dvs-history-data-worker`, queries and transforms rows off the GUI thread.
- `PaperTradePrepareWorker`: opens SQLite inside `dvs-paper-data-worker`, prepares statistics, diagnostics and rows off the GUI thread.
- Single-flight per owner with generation-per-submit, latest-request-wins pending slot and stale-payload rejection.
- GUI rendering is chunked (`history=16 rows`, `paper=12 rows`) and each commit is measured against 25 ms.
- Telemetry: `artifacts/runtime/gui_data_prepare.jsonl`.

## Runtime evidence required
Audit `prepare_submitted`, `prepare_completed`, `stale_payload_rejected`, and `gui_commit` events. Worker prepare time is not a GUI failure; only `gui_commit_ms > 25` is a GUI budget violation.

## Safety
Decision Engine remains frozen and unchanged. No live execution is enabled.
