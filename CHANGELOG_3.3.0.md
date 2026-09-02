# DVS AI Alpha 3.3.0 — Async Core Shadow Adapter Foundation

## Scope

This release implements two preparatory changes only. It does **not** connect
`DVSAICore` to `MainWindow`, does not transfer paper authority, and does not
add any LIVE execution path.

## Test baseline cleanup

- Removed historical release-label assertions from legacy feature tests.
- Version identity now checks `dvs_ai.__version__ == APP_VERSION`.
- Mixed version/safety tests were split so that safety expectations remain
  hard-coded:
  - `execution_mode == "PAPER"`
  - `execution_live_enabled is False`
  - `auto_paper_execution_enabled is False` where applicable.
- Full suite baseline: **638 passed**.

## Async shadow adapter foundation

Added `dvs_ai/ui/core_runtime_adapter.py`:

- `CoreCycleRequest` — immutable and shadow-only.
- `CoreCycleResultViewModel` — immutable, read-only GUI result.
- `CoreCycleFailureViewModel` — immutable fail-closed error result.
- `CoreRuntimeAdapter.run_cycle_async()` — the only execution-facing public
  operation exposed to GUI code.
- `QThread` worker execution; the GUI thread is not blocked.
- Latest-request-wins coalescing.
- Stale-result rejection by request id.
- GUI quantity is always projected as `0.0`.
- No exported authorize, resize, open-position, submit-order, place-order,
  exchange, ledger, or mutable core handle.

## Explicit non-goals

- No import of `DVSAICore` into `main_window.py`.
- No authority transfer from the legacy engine.
- No connection to the existing Paper Trade table.
- No change to exchange, deployment, testnet, or LIVE order boundaries.
