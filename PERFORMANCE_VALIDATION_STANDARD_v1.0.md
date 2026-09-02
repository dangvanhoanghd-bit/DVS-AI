# DVS AI Performance Validation Standard v1.0

## Scope
This frozen standard applies symmetrically to the G1 control build and G2 candidate build. It changes telemetry only; Decision Engine, scoring thresholds, PAPER execution boundaries, scan logic and trading rules are unchanged.

## Session validity prerequisites
An official PASS/FAIL comparison is valid only when:

- both sessions run continuously for at least 60 minutes;
- duration difference does not exceed 15%;
- both use the same machine, universe, scan interval, mode and interaction script;
- G1 and G2 run sequentially, not simultaneously;
- JSONL integrity errors, writer errors and dropped records are all zero.

A session below these requirements is reference-only and cannot produce an official PASS/FAIL decision.

## Lightweight symmetric instrumentation
Both builds use the same telemetry implementation:

- GUI-thread QTimer samples process metrics every 20 seconds;
- GUI-thread 250 ms timer measures event-loop delay;
- a dedicated single writer thread is the only code allowed to append the session JSONL file;
- every record contains session_id and build label;
- old active snapshot folders are moved to snapshots/_archive/ at startup, never deleted.

## Files

- runtime_metrics_<session_id>.jsonl
- AB_TEST_MANIFEST_<session_id>.json
- heartbeat.json
- runtime_status.json
- snapshots/<current_session_id>/snapshot_*.json
- snapshots/_archive/<historical_session_id>/...

## Operational definitions

- event-loop stall: event_loop_lag_ms >= 500 ms
- Not Responding proxy: event_loop_lag_ms >= 5000 ms
- CPU acceptance: G2 mean process CPU may not exceed G1 by more than 10 percentage points
- RAM acceptance: G2 mean RSS may not exceed G1
- Event-loop acceptance: G2 P95 and P99 must be lower than G1
- Native crashes and unrecovered deadlocks: zero

## Audit rule
Auditors must filter records by the session_id stored inside every record. Folder names and glob results are not trusted as the sole session boundary.
