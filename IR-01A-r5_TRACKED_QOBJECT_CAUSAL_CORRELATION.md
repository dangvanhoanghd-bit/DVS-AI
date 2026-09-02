# IR-01A-r5 — Tracked QObject Causal Correlation

Build: `RC6.4.7H-r2-IR-01A-r5-TRACKED-QOBJECT-CAUSAL-CORRELATION`

## Scope
Observe-only correlation between tracked QObject/QThread IDs, CPython DummyThread wrappers, callback execution, QThread finish, QObject destruction, and process exit.

## New artifacts
- `artifacts/runtime/tracked_qobject_correlation.jsonl`
- `artifacts/runtime/tracked_qobject_correlation_summary.json`

## Safety
- No mutation of `threading._active`, `_limbo`, or `_dangling`.
- No QObject dereference after `destroyed`.
- No changes to signal topology, thread affinity, ownership, or shutdown order.
- Tracked IDs are stable within one process session and derive from registration name, Python object ID, and C++ pointer.
