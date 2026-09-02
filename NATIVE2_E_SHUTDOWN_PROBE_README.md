# NATIVE2-E — Shutdown Origin & Thread Lifecycle Probe

Baseline: NATIVE2-D Runtime Telemetry GUI Hardening.

Purpose: observe the first shutdown signal and thread state before CPython reaches `Py_AtExit` / `Py_DumpTraceback`.

## New outputs

- `artifacts/runtime/shutdown_probe.jsonl`
- `artifacts/runtime/shutdown_thread_snapshots.jsonl`
- `artifacts/runtime/shutdown_qt_messages.log`
- `artifacts/runtime/shutdown_unhandled_exception.log`

## Observed lifecycle points

- `run_entry`, `app_main_enter`
- QApplication/MainWindow creation
- Qt `lastWindowClosed`, `aboutToQuit`, Quit/Close/DeferredDelete events
- `sys.exit()` and `os._exit()` calls with Python stacks
- `sys.excepthook` and `threading.excepthook`
- `app.exec()` enter/return/exception
- each existing finalizer step
- Python `atexit`
- all live Python threads and their stacks at critical boundaries

## Scope

Observe-only. No scanner, Decision Engine, scoring, Paper Trade, network, or execution-authority logic is changed.
