# NATIVE2-G1 — Stable Performance Reconciliation

## Purpose
Restore the proven GUI responsiveness work on top of the NATIVE2-F native-crash isolation baseline.

## Integrated changes

1. **RC6.5 Cooperative Scan Result Pipeline**
   - The scan-result callback performs constant-time ingestion.
   - Side effects are drained FIFO, one item per event-loop turn.
   - Finalization waits until the deferred side-effect queue is empty.
   - Existing identity, recorder, capture, and Paper Trade ordering contracts are retained.

2. **RC6.4.2-r3 Truth Operational Data Worker**
   - Operational/readiness aggregation moves to a persistent data-only worker.
   - Qt widget mutation remains on the GUI thread.
   - In-flight control, request coalescing, generation ordering, and duplicate throttling are retained.

3. **NATIVE2-F crash isolation retained**
   - Periodic in-process native all-thread traceback dumping remains disabled.
   - Shutdown probe and lightweight runtime telemetry remain available.

## Deliberately not integrated in G1

The Auto Paper I/O worker and later presentation/recorder branches are not merged in this first controlled build because those historical patches diverged from separate main-window branches. They will be considered only after G1 runtime evidence confirms clean startup, scan completion, identity continuity, and no native crash.

## Unchanged safety boundary

- Decision Engine and scoring logic
- qualification thresholds
- Paper Trade business rules and database schema
- PAPER/observe-only execution authority
- capture-key identity contract

## Acceptance test

1. Extract to a new folder.
2. Run at least five full scan/finalization cycles.
3. Confirm the process does not exit.
4. Observe whether short Not Responding events decrease.
5. Return `artifacts/runtime` if a stall, shutdown, or identity error occurs.
