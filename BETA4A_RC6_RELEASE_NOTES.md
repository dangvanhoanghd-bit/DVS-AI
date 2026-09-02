# DVS AI Beta 4A RC6 — Identity Delivery & UI Thread Hardening

## Runtime fixes

1. Auto Paper no longer treats delayed Unified identity publication as permanent failure.
2. Stable `(scan_id, symbol)` capture keys remain queued until identity succeeds or the capture worker emits an explicit failure.
3. Added identity latency and capture queue-depth telemetry:
   - `AUTO_PAPER_IDENTITY_DELAYED`
   - `UNIFIED_IDENTITY_PUBLISHED ... latency_ms=... pending=...`
4. Removed synchronous `paper_trade_service.update_open_trades()` calls from GUI callbacks.
5. Paper/outcome resolution now uses the persistent, coalescing `OutcomeResolutionCoordinator` worker.
6. UI refresh occurs only after the worker commits outcome changes.

## Safety properties retained

- Decision Engine logic is unchanged.
- Auto Paper remains fail-closed on explicit capture failure.
- Candidate/Outcome/Feature identity remains based on stable business keys, not Python object identity.
- No order-execution authority was enabled.

## Required validation

Run a fresh 6–24 hour burn-in and verify:

- zero `AUTO_PAPER_IDENTITY_TIMEOUT` events;
- zero opportunities permanently skipped only because identity was delayed;
- identity latency p50/p90/p99 and queue depth remain bounded;
- P99 UI event-loop lag below 250 ms;
- maximum UI lag below 1,000 ms.
