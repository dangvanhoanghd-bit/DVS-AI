# RC6.4.7 — GUI, Memory and Auto-Paper Identity Diagnostics

## Scope
Observe-only diagnostics layered on the runtime-verified RC6.4.6C stable generation-token cleanup. Decision Engine and paper-only safety boundaries are unchanged.

## New evidence
- `identity_diagnostics.jsonl`: per-key capture, queue, publish, defer, warning and consumption state.
- `collection_snapshots.jsonl`: 20-second collection-size snapshots, Qt timer/thread counts and table capacity.
- `callback_attribution.jsonl`: completed GUI callback duration, nested depth, scan and cycle identity.
- `scheduler_drift.jsonl`: adds `last_completed_callback` and correlation gap, avoiding the structural all-null limitation of active-only sampling.

## Identity warning reason codes
- `DELAYED_CAPTURE_SERVICE_PENDING`
- `DELAYED_LOCAL_TRACKER_WITH_SERVICE_IDLE`
- `DELAYED_STATE_ALREADY_COMPLETED`
- `DELAYED_IDENTITY_MISSING_WITHOUT_PENDING_TRACKER`

## Frozen behavior
- Generation-token cleanup lifecycle is unchanged.
- No `self.sender()`, Python `is`, or object id participates in cleanup authority.
- Decision Engine SHA-256 remains unchanged.
- Execution remains paper-only.
