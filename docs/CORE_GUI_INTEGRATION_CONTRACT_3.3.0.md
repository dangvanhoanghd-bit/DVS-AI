# Core / GUI Integration Contract — Foundation

## Current boundary

`MainWindow` remains on the legacy analysis path. The new adapter is an
unwired foundation for a future shadow comparison.

## Threading rule

`DVSAICore.run_cycle()` must never be called directly from a GUI event handler.
All calls go through `CoreRuntimeAdapter.run_cycle_async()` and execute on a
worker `QThread`.

## Capability rule

The GUI receives immutable view models only. It cannot obtain an executable
quantity or call authorization, risk sizing, order submission, exchange, or
ledger mutation operations through the adapter.

## Queue rule

Only one cycle runs at a time. While active, repeated requests are coalesced;
only the most recent pending request is retained. Results whose request id is
no longer current are discarded.

## Authority rule

This foundation is shadow-only. Paper authority remains unchanged. Any future
authority handover requires a separately governed, hash-verified profile and
ledger event; it cannot be achieved by this adapter or a GUI config toggle.
