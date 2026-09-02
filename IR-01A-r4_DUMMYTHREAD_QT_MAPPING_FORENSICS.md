# IR-01A-r4 — DummyThread Registry ↔ Qt Thread Mapping Forensics

Build: `RC6.4.7H-r2-IR-01A-r4-DUMMYTHREAD-QT-MAPPING-FORENSICS`

## Scope

Observe-only instrumentation that correlates CPython `_DummyThread` wrappers with live Qt/native thread wrappers at actual callback entry points. It does not mutate `threading._active`, `_limbo`, `_dangling`, QObject ownership, signal connections, or shutdown order.

## New artifacts

- `artifacts/runtime/dummy_thread_registry_forensics.jsonl`
- `artifacts/runtime/qt_thread_mapping_forensics.jsonl`

## Safety

- Registry data is snapshot-only. No entry is removed or modified.
- Qt metadata is captured while wrappers are live.
- No QObject is dereferenced after `destroyed`.
- Decision Engine remains unchanged.
