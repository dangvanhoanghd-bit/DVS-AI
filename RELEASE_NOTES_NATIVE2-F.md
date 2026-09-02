# DVS AI Beta4A RC6.1 Test-A NATIVE2-F
## Freeze Dump Native Crash Isolation

### Confirmed fault isolated
The periodic in-process call to `faulthandler.dump_traceback_later(..., repeat=True)` has been removed from the GUI process. WinDbg and runtime evidence tied the process termination to `python312!Py_DumpTracebackThreads / Py_DumpTraceback` with access violation `0xC0000005` while the 10-second freeze watchdog fired.

### Behavioral scope
- `SessionFreezeDump` now operates in `log_only_native_dump_disabled` mode.
- Artifact paths and metadata remain available for telemetry compatibility.
- No periodic native traceback dump is scheduled.
- No all-thread traceback dump is triggered by this component.
- Scanner, scoring, Decision Engine, Paper Trade, Outcome Pipeline and execution authority are unchanged.

### Test objective
Run one manual scan and verify that the process no longer exits near the 10-second freeze-watchdog boundary. Preserve `artifacts/runtime` for follow-up UI-stall analysis.
