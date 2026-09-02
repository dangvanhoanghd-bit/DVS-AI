# Sprint A2 V2.4 — Startup & Finalization Decongestion

## Scope

- Preserves the independently verified V2.3.1 Paper Trade baseline.
- Defers heavy workspace builders until after the first real window paint.
- Defers OrderFlowRuntime.start() until after first paint.
- Adds startup_decongestion v2 milestones: lightweight_shell_ready, window_show_event, first_paint, per-workspace steps.
- Removes duplicate nested callback attribution for finalization_commit_entry.
- Keeps the table delta commit in the primary callback, while moving retention snapshots, detail projection, auto-paper queue preparation, and qualification submission to a later event-loop turn.
- Moves core_shadow_agreement_store.metrics() to a dedicated persistent QThread.
- Adds finalization_callback_forensics.jsonl and qualification_callback_forensics.jsonl with queue/execution separation.

## Acceptance targets

- Startup first-paint lag < 1.5 s and startup Not Responding = 0.
- Finalization GUI callback P95 < 250 ms.
- Qualification GUI callback P95 < 250 ms.
- Paper qt_commit max < 100 ms; no multi-second Paper regression.
- Release identity mismatch = 0; Decision Engine hash unchanged; shutdown survivors = 0.

## Status

Source validation PASS. Runtime effectiveness pending. Production approval not granted.
