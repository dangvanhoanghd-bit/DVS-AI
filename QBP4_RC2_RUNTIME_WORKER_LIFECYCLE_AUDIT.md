# QBP-4 RC2 Runtime Worker Lifecycle Hardening

## Runtime evidence

Real soak-test logs showed a repeatable cleanup race:

```text
RuntimeError: libshiboken: Internal C++ object (Worker) already deleted.
_scan_run_requested.disconnect(current_worker.run)
```

The worker emits `finished` in the persistent scan QThread. Its `deleteLater`
can destroy the native QObject before the queued GUI cleanup slot executes.
Dereferencing `current_worker.run` at that point is unsafe.

## Fix

The cleanup path no longer dereferences or explicitly disconnects the deleted
worker. Qt removes connections automatically when the receiver QObject is
destroyed. Stale-sender protection remains, and reference cleanup is guarded by
`try/finally` so the cycle marker is always reset.

## Scope

- Persistent QThread architecture retained.
- Scanner calculation unchanged.
- Quantum QBP-0 through QBP-4 unchanged.
- Execution remains observe-only and locked.
- Decision Engine unchanged.

Decision Engine MD5:

```text
72cf7d54e1ed6369400683358da8c0ef
```
