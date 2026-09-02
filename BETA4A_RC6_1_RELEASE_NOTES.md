# DVS AI Beta 4A RC6.1 — Telemetry Export & Collector Alignment

## Scope
- Deterministic runtime telemetry under `artifacts/runtime/`.
- Atomic `runtime_status.json` and `heartbeat.json` writes.
- Session-isolated minute snapshots.
- Collector reads the fixed telemetry contract before falling back to process scanning.
- Explicit runtime states: `RUNTIME_NOT_STARTED`, `RUNTIME_HEARTBEAT_STALE`, `RUNTIME_CONNECTED`.

## Runtime files
- `artifacts/runtime/runtime_status.json`
- `artifacts/runtime/heartbeat.json`
- `artifacts/runtime/snapshots/<session_id>/snapshot_*.json`

## Safety
- Decision Engine and scoring logic are unchanged.
- Orders remain locked.
- Telemetry writes use temporary files plus atomic replacement.
