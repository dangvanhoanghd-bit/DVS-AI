# IR-01A-r1 Signal Path Forensics

Build: `RC6.4.7H-r2-IR-01A-r1-SIGNAL-PATH-FORENSICS`

## Scope

Forensic-only hardening for queued worker delivery after the PID 1868 regression.
Decision Engine, Foundation logic, Research Platform, and Scientific Method remain unchanged.

## Added

- Real-path startup queued-signal self-test for History Prepare, Paper Prepare, and Auto Paper.
- Fail-fast pipeline disablement when any probe path misses its deadline.
- `signal_path_forensics.jsonl` with connect/emit/worker-entry/result-emit/GUI-slot events.
- Immediate sender, receiver, object-id, thread-id, and thread-affinity capture.
- Worker-side probe paths that do not touch SQLite or PaperTradeService.
- No automatic reconnect or silent repair.

## Runtime protocol

Run 10–15 minutes only. Do not perform a long burn-in until the startup gate and all three real signal paths pass.
