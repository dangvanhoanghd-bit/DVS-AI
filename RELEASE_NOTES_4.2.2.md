# DVS AI Alpha 4.2.2 — Scan Runtime Resource Lifecycle Fix

Baseline: DVS AI Alpha 4.2.1 Audit Hardening Release.

## Scope

This maintenance release fixes the lifecycle of the one-shot primary scan
`QThread` and `Worker` created by each manual or automatic scan cycle.

- Parent the scan `QThread` to the main window.
- Schedule the scan worker and thread QObject wrappers for `deleteLater()`.
- Clear the active worker/thread references when the thread finishes.
- Reject stale cleanup signals defensively.
- Record bounded per-cycle lifecycle telemetry without retaining historical
  worker, thread, result, or DataFrame objects.

## Non-goals and frozen boundaries

- No Decision Engine source change.
- No indicator, score, threshold, ranking, entry, or market-bias change.
- No change to scan universe, concurrency policy, or API request behavior.
- No change to Research/Governance logic.
- Execution remains PAPER-only; live execution remains disabled.

Frozen Decision Engine MD5:

`72cf7d54e1ed6369400683358da8c0ef`
