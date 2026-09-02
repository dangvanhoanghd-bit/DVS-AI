# DVS AI Alpha 2.23.0 — Async Finalization & Atomic UI

## Confirmed freeze source

The full end-of-scan pipeline ran synchronously in `_on_finished_impl()` on the
Qt GUI thread:

- market brief
- market-bias gates
- confidence calibration
- opportunity ranking
- microstructure hydration
- microstructure adjustment
- second ranking
- complete table update
- Auto Paper consideration
- History/Paper/Learning refresh

Windows can mark the application "Not Responding" while that single GUI callback
is running.

## Changes

- Added `FinalizationWorker` on a dedicated `QThread`.
- Worker performs all non-widget finalization and emits one result payload.
- MainWindow applies finalized results in one atomic table transaction.
- Added O(1) `symbol -> row` index.
- Sorting happens once after the atomic commit.
- Table signals and repaint remain blocked during the commit.
- Auto Paper is processed in batches of five via the Qt event loop.
- Open Paper Trade maintenance runs after the critical UI commit.
- MarketChart suppresses identical renders and redundant overlay updates.

## Invariant

Background workers never touch Qt widgets. GUI mutation remains exclusively on
the MainWindow thread.

No Decision, Smart Entry, risk, ranking or execution formula was changed.
