# DVS AI Alpha 4.2.5 — Persistent Scan QThread / Dummy Wrapper Accumulation Fix

## Evidence-driven root cause
4.2.4 runtime attribution showed exactly one new `Dummy-*` entry per scan cycle while:
- `dvs-scan` executor threads returned to zero,
- `executor_drained=True`,
- the one-shot Qt worker and QThread were released.

CPython creates `_DummyThread` bookkeeping objects when Python executes on a native thread not created by `threading.Thread`. Those wrappers are intentionally retained by CPython. Recreating the scan `QThread` every cycle therefore produced apparent unbounded Python-thread growth even though the native Qt threads had ended.

## Fix
- Create one private, persistent `QThread` named `dvs-scan-runtime` for the application lifetime.
- Create and delete one `Worker` per scan cycle on that same QThread.
- Queue each run through a Qt signal.
- Disconnect the completed worker and release its Python reference after every cycle.
- Stop and join the persistent QThread during application shutdown.

## Scope invariants
- Decision Engine unchanged. Frozen MD5: `72cf7d54e1ed6369400683358da8c0ef`.
- Scanner calculations, thresholds, scoring, risk logic and execution authority unchanged.
- PAPER mode and orders-locked safety posture unchanged.
