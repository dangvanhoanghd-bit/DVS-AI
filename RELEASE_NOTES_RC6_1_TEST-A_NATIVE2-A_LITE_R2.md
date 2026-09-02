# DVS AI Beta4A RC6.1 Test-A NATIVE2-A Lite R2

## Scope
Network Startup Guard only. Decision Engine and scoring logic are unchanged.

## Changes
- Caps scan HTTPS concurrency at 4 workers for this audit cohort.
- Adds `artifacts/runtime/network_startup.jsonl`.
- Records `snapshot_fetch_enter`, `snapshot_fetch_exit`, and `snapshot_fetch_error`.
- Updates GUI immediately when executor starts and requests are submitted.
- Progress now reflects completed futures directly (`i/total`).
- Retains NATIVE2-A frame ownership telemetry unchanged.

## Expected first-run UI
- `Đang tải snapshot thị trường · 4 workers active`
- `Đã gửi N/N yêu cầu · đang chờ snapshot (4 workers)`
- Progress advances as each snapshot/coin completes.

## Audit boundary
No changes to Decision Engine, frame cache return semantics, Paper Trade, outcome pipeline, or execution mode.
