# NATIVE2-G1C Stable Clean

## Purpose
Restore production responsiveness while retaining the NATIVE2-F native-crash isolation and NATIVE2-G1 cooperative optimizations.

## Removed from hot path
- Shutdown lifecycle probe and thread snapshots.
- Session freeze-dump artifact lifecycle.
- RC6.2/RC6.3 callback attribution wrappers and synchronous JSONL writes.
- GUI event-loop watchdog polling and per-section profiling.
- Native `faulthandler` all-thread fault dumping.

## Retained
- Cooperative scan-result pipeline.
- Truth operational data worker.
- Runtime heartbeat/process telemetry.
- Signal recorder worker.
- Decision Engine, scoring, thresholds, PAPER/observe-only boundaries.

## Test objective
Run from a new folder. Verify startup, five scan cycles, GUI interaction during scan, Paper/Outcome finalization, and absence of process termination.
