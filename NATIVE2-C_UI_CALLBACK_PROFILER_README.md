# DVS AI Beta4A RC6.1 Test-A — NATIVE2-C UI Callback Profiler

Observability-only diagnostic build based on NATIVE2-B Stage Boundary Probe.

## New runtime evidence

`artifacts/runtime/ui_callback_profile.jsonl`

Events:
- `callback_enter`
- `callback_exit`
- `section_sample`
- `event_loop_stall`

Focused callback names:
- `scan_result_callback`
- `scan_result_recorder`
- `scan_result_truth_dashboard_set`
- `scan_result_schedule_aggregate`
- `aggregate_refresh_batch`
- `stream_table_batch_commit`
- `stream_table_sort`
- `stream_row_index_rebuild`
- existing profiled refresh/finalization sections

No trading thresholds, Decision Engine behavior, execution authority, or scan algorithms were intentionally changed.

## Test procedure
1. Run `START_DVS_AI`.
2. Press `Quét dữ liệu` once.
3. If the UI becomes Not Responding or the process exits, wait 60–90 seconds when possible.
4. Close the application and zip `artifacts/runtime`.
5. The primary file is `ui_callback_profile.jsonl`; also include `stage_boundary.jsonl`, freeze dumps, heartbeat, and runtime status.
