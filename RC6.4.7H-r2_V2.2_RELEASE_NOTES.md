# Sprint A2 V2.2 — GUI Event-Loop Blocker Attribution

Diagnostic-only candidate. No Decision Engine or trading semantics changes.

## Added

- `InstrumentedApplication`, a `QApplication` subclass that times every Qt event dispatch through `notify()`.
- Slow-event attribution by receiver class, object name, event type, and dispatch duration.
- A 100 ms GUI pulse with late-pulse telemetry.
- A background watchdog that captures the GUI Python stack when the pulse is overdue or a Qt event remains active for at least 1 second.
- One-second event-dispatch summaries to identify dense chains of short events.
- Bounded asynchronous JSONL writer; no synchronous disk I/O in `notify()`.

## Runtime evidence file

`artifacts/runtime/gui_event_loop_forensics.jsonl`

Principal events:

- `forensics_started`
- `event_dispatch_slow`
- `event_loop_pulse_late`
- `event_loop_watchdog_sample`
- `event_dispatch_window`
- `writer_queue_drop`
- `forensics_stopped`

## Classification

- Source instrumentation correctness: source-validated
- Root-cause visibility: pending runtime
- Performance effectiveness: not evaluated
- Production approval: not granted
