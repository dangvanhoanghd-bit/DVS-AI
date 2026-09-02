# RC6.4.7H-r2 — TS12-PFT-001 Single-Flight Worker

## Scope

This patch removes synchronous selected-deep payload measurement from the GUI
execution path without changing the Decision Engine.

## Implementation

- `PayloadFootprintTelemetry.snapshot()` is now a non-blocking submit operation.
- A single daemon worker performs the bounded selected-deep measurement.
- No queue is allowed: concurrent submissions are explicitly emitted as
  `snapshot_busy_drop` (fail-open).
- Every submit has a unique, monotonically increasing generation and request ID.
- Lifecycle telemetry includes submit/start/terminal events, thread identity,
  queue depth, callback overhead, worker duration, and reference-release timing.
- Terminal records contain `measurement_finished_monotonic`,
  `reference_release_monotonic`, and `reference_release_ms` in the same record.
- Live-owner safety uses optimistic version validation. Measurements are marked
  `invalidated_owner_changed` if shallow owner identity/edge tokens change while
  traversal is in progress. This is deliberately not described as deep immutable
  ownership.
- Request references are cleared in `finally` before the terminal record is
  written.

## Runtime invariants

- `snapshot_submit = snapshot_started + snapshot_busy_drop`
- each started request has exactly one terminal event
- generations are unique and monotonically increasing
- all `owner_footprint_snapshot` records must have `is_gui_thread=false`
- worker backlog is zero; only one active measurement is permitted

## Audit status

This package is a source implementation candidate. Runtime causal closure and
Technical Standard freeze remain pending burn-in A/B evidence.
