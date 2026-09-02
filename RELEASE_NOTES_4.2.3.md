# DVS AI Alpha 4.2.3 — Executor Drain & Sleep/Resume Hardening

Baseline: DVS AI Alpha 4.2.2.

## Runtime-only changes

- `Worker.run()` now performs one authoritative `ThreadPoolExecutor.shutdown(wait=True, cancel_futures=True)` in the worker thread.
- `Worker.stop()` no longer races executor shutdown from the GUI thread.
- Added named-thread telemetry for `dvs-scan-*` and an `executor_drained` assertion per cycle.
- Added Windows sleep/hibernate resume-gap detection. The first timer tick after a large gap defers the next automatic scan and resets the countdown.
- Existing provider connect/read timeouts remain unchanged and finite.

## Frozen scope

No Decision Engine, score, threshold, ranking, indicator, market-bias, or execution-authority changes. PAPER-only safeguards remain unchanged.
