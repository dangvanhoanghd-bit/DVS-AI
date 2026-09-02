# IR-01A-r7 — Native Crash Capture

This candidate moves the investigation below Python telemetry. The external PLF supervisor launches the child with `DEBUG_ONLY_THIS_PROCESS`, captures second-chance native exceptions, and writes a Windows MiniDump before the faulting process is allowed to terminate.

Artifacts:
- `artifacts/process_lifetime/native_crash_capture.jsonl`
- `artifacts/process_lifetime/native_crash_capture_<session>.json`
- `artifacts/process_lifetime/native_crash_<session>_pid...dmp`
- `artifacts/runtime/application_qobject_census.jsonl`

The dump is intentionally not a full-memory dump. It includes thread info, module headers, unloaded modules, handles, process/thread data, full memory map information, and indirectly referenced memory. Analyze it with WinDbg using `!analyze -v`, `.ecxr`, `k`, `~* k`, and `lm`.

No trading logic, Decision Engine logic, signal topology, Worker/QThread lifecycle, or CPython registry is modified.
