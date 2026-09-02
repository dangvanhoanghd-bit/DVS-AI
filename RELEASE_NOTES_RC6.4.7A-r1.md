# RC6.4.7A-r1

- GC callback changed to enqueue-only bounded ring buffer.
- One telemetry writer aggregates GC data once per second.
- Active callback monitor is enqueue-only.
- Added enter/done/failed telemetry around each finalization refresh.
- SQLite connections use timeout=3.0 and PRAGMA busy_timeout=3000.
- Decision Engine unchanged.
