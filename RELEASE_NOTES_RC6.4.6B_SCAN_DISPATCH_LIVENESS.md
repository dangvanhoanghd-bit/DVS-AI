# RC6.4.6B — Scan Dispatch Liveness Instrumentation

## Scope
Observe-only/runtime instrumentation. Decision Engine behavior, scoring, thresholds, Paper execution locks, provider retry policy, and circuit-breaker policy are unchanged.

## Implemented
1. Restored lightweight in-memory GUI callback context with nested-call-safe `try/finally`; no synchronous callback JSONL writes.
2. Added exception boundary to scan-result side-effect drain and a re-entrancy-protected reconciliation step that always re-arms draining or schedules completion.
3. Added lifecycle trace checkpoints for worker finished emission, cleanup entry, independent worker identities, identity mismatch, thread reset, cleanup exit, result-drain completion, and finalization start.
4. Added launch-decision reason codes including `BLOCKED_THREAD_RUNNING`, `BLOCKED_SCAN_RUNTIME_UNAVAILABLE`, `BLOCKED_FINALIZATION_RUNNING`, and `LAUNCH_ACCEPTED`.
5. Confirmed and instrumented global exception hook installation before `QApplication` creation.
6. Added runtime `code_identity.json` with build ID and SHA-256 values for key source files, including the frozen Decision Engine.

## Runtime evidence
- `artifacts/runtime/scan_dispatch_liveness.jsonl`
- `artifacts/runtime/scheduler_drift.jsonl` with live `active_callback`
- `artifacts/runtime/exception_hook.jsonl`
- `artifacts/runtime/code_identity.json`
- `logs/gui_crash.log`

## Audit status
Implementation is not declared runtime-verified. A new burn-in is required to determine why cycle 19 was not dispatched.
