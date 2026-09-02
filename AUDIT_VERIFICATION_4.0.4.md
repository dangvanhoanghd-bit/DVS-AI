# DVS AI Alpha 4.0.4 — Audit Verification

Verification date: 2026-07-20

## Verified fixes

1. Decision Graph confidence conservation
   - `QualificationReplayService.build()` creates `baseline_confidence` when both `reason_codes` and `event_names` are empty and persisted confidence is non-zero.
   - The sum of all graph-node contributions remains equal to the persisted confidence.
   - Mixed reason/event scenarios do not create the baseline node and do not double-count confidence.
   - An explicit `GRAPH_CONFIDENCE_INVARIANT_FAILED` diagnostic is emitted if conservation is ever violated.

2. Qualification Batch Runner observability
   - Pending queue is bounded by `max_pending_batches=2` by default.
   - Queue saturation is rejected explicitly with `QUEUE_FULL`; batches are not silently dropped.
   - A single persistent `QThread` owns the worker.
   - Per-item exceptions are no longer swallowed.
   - Each failure creates a structured `QualificationBatchItemFailure`, writes full traceback to the rotating failure journal, emits `batch_item_failed`, and logs via `LOGGER.exception()`.

3. Evidence Center / SHA-256 integrity
   - PASS, LEGACY_UNSEALED, and FAILED remain distinct.
   - Canonical payload verification detects direct SQL tampering.
   - Schema migration remains backward-compatible with pre-seal databases.

4. Scientific Qualification Report
   - Governance recommendation requires zero integrity failures.
   - One tampered row invalidates READY governance even when raw qualification metrics otherwise pass.
   - PDF escaping and structural tests pass.

5. Shadow Replay
   - Replay navigation is bounds-clamped.
   - Auto replay terminates safely.
   - Integrity failure is surfaced as `REPLAY INVALID · INTEGRITY REVIEW REQUIRED`.

## Test results

- Targeted qualification/audit suite: 24 passed
- Complete project suite: 686 passed
- Failures: 0

## Release status

AUDIT VERIFIED — suitable as the official DVS AI Alpha 4.0.4 baseline for continued development.
