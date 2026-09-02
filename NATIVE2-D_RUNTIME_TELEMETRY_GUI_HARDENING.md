# NATIVE2-D — Runtime Telemetry GUI Hardening

## Evidence-based root cause
The freeze dump from session `20260726_085205_c4fd0ed6` repeatedly captured the Qt main thread in:

`RuntimeTelemetryExporter.publish_heartbeat -> _collect -> psutil.Process.open_files -> psutil._pswindows.open_files`

`RuntimeTelemetryExporter` is owned by the main window and its `QTimer` callbacks run on the GUI thread. On Windows, `open_files()` can block while enumerating process handles. This prevented Qt from processing Windows messages and produced `Not Responding` with CPU near 0%.

## Change
- Disable `psutil.Process.open_files()` enumeration in the GUI-thread heartbeat path.
- Preserve the telemetry schema field as `open_files: null`.
- Add `open_files_status: disabled_gui_thread_safety`.

## Unchanged
- Decision Engine
- Scan and scoring algorithms
- Paper Trade and Outcome Pipeline
- Network Startup Guard
- Stage Boundary Probe
- UI Callback Profiler
- PAPER / observe-only execution policy
