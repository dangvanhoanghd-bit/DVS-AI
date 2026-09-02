# RC6.1 Baseline — FIX-DUMP Minimal R1

Baseline source: `DVS_AI_BETA4A_RC6_1_TELEMETRY_EXPORT_COLLECTOR_ALIGNMENT(4).zip`.

Changes are evidence-only:

- Creates a new session-scoped dump at `artifacts/runtime/freeze_dumps/<session_id>/freeze_dump.log`.
- Creates matching `freeze_dump_metadata.json` containing session ID, PID, start time, executable, working directory, and dump path.
- Writes the current dump paths into `runtime_status.json`.
- The burn-in collector copies freeze evidence only when session ID, PID, path, metadata, and dump header all match.
- Writes `evidence_status.json` with `VALID_CURRENT_SESSION`, `STALE_OR_MISMATCHED`, or `NOT_AVAILABLE`.

No scanner, network timeout, retry, Decision Engine, Outcome, Paper Trade, or UI behavior was changed.
