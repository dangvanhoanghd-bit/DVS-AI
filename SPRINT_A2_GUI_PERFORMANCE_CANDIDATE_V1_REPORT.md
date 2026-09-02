# Sprint A2 — GUI Performance & Event Loop Optimization — Candidate V1

## Scope

This candidate preserves the frozen Decision Engine and changes only GUI refresh scheduling in `dvs_ai/ui/main_window.py`.

## Source changes

- Added a single-flight coalescing queue for named GUI refreshes.
- Added a single-shot 16 ms dispatcher timer.
- Executes at most one heavy refresh per event-loop turn.
- Collapses duplicate pending refresh requests.
- Replaced the synchronous five-refresh burst after scan finalization.
- Replaced the synchronous two-refresh burst after outcome resolution.
- Added `gui_refresh_dispatch.jsonl` telemetry.

## Telemetry events

- `refresh_queued`
- `refresh_coalesced`
- `refresh_executed`

`refresh_executed` records:

- `refresh_name`
- `reason`
- `measurement_ms`
- `budget_ms` (25 ms)
- `budget_exceeded`
- `queue_size_after`
- `outcome`
- `failure_type`

## Safety constraints

- No `wait()` or blocking loop added.
- No `terminate()` added.
- Existing GUI-only refresh functions remain on the GUI thread.
- Decision Engine unchanged.
- Shutdown UX Candidate V1 behavior retained.

## Verification

- Python compile: PASS
- Targeted tests: 9 passed
- Runtime verification: REQUIRED

## Build identity

`RC6.4.7H-r2-GUI-PERFORMANCE-CANDIDATE-V1`

## Audit status

- Source implementation: PASS
- Runtime effectiveness: PENDING
- Production approval: NOT GRANTED
