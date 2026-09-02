# QBP-4 RC4 Finalization Diagnostics

Built directly from the audited RC3 source.

## Scope
- Adds structured `FINALIZATION_GUI_COMMIT_METRICS` telemetry.
- Adds per-process `session_id`, PID, scan cycle and commit IDs.
- Measures table clear, row build, sort, row-index rebuild, GUI restore and total commit time.
- Logs table/result sizes and cell-diff counters for correlation analysis.
- Suppresses >10 second watchdog gaps from UI stall statistics while preserving a dedicated log line.
- Fixes the Windows launcher title/echo without CMD metacharacters.

## Invariants
- Decision Engine unchanged.
- Thresholds unchanged.
- MAIN/SHADOW policy unchanged.
- Quantum governance and execution authority unchanged.
