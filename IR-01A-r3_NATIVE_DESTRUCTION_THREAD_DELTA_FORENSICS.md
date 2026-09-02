# IR-01A-r3 — Native Destruction & Thread Delta Forensics

Build: `RC6.4.7H-r2-IR-01A-r3-NATIVE-DESTRUCTION-THREAD-DELTA-FORENSICS`

## Added evidence

- `artifacts/runtime/thread_delta_forensics.jsonl`
  - compares consecutive Python thread snapshots by `(thread_ident, native_id)`
  - records added, removed and persisting thread identities
  - preserves first/last-seen timestamps and stack snapshots
- `artifacts/runtime/native_object_destruction.jsonl`
  - registration metadata captured while QObject wrappers are valid
  - C++ pointer, parent and thread-affinity snapshot
  - `shiboken6.isValid()` snapshots at shutdown phases
  - QThread `finished` and QObject `destroyed` timeline
  - destroyed callbacks never dereference the destroyed QObject

## Safety boundary

Observe-only instrumentation. Decision Engine and trading logic are unchanged.
