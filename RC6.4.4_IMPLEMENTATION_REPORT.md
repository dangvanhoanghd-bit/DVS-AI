# DVS AI RC6.4.4 — Network Resilience & Scan Lifecycle Integrity

## Scope

Runtime/infrastructure-only patch. Decision Engine and trading logic were not modified.

## Implemented

- Explicit monotonic `DeadlineBudget`; no `threading.local()` deadline state.
- `BoundedRetry` with capped `Retry-After`.
- Explicit request retry loop so request, backoff, Retry-After and snapshot operations share bounded deadlines.
- `PROVIDER_OPERATION_DEADLINE_EXCEEDED` classification.
- Provider evidence JSONL with phase, symbol, endpoint, status, raw/applied Retry-After and elapsed time.
- Explicit future identity: `scan_cycle_id + executor_generation + symbol`.
- Future lifecycle: `QUEUED → RUNNING → FINISHED`; execution start is recorded inside the worker thread.
- `dispatch_latency_ms` recorded independently from execution age.
- Quantified orphan threshold with absolute floor and one-worker exception.
- Executor quarantine using `shutdown(wait=False, cancel_futures=True)`.
- Separate stale-cycle and quarantined-generation result classifications.
- Stage-boundary producer/write/error counters and rate-limited error reporting.

## Independent adversarial tests executed in build environment

- Retry-After 300 seconds is capped.
- Total provider operation deadline bounds repeated 429 responses.
- Snapshot deadline failure is fail-fast and later phases are not called.
- Stage-boundary write failure increments integrity counters.
- Future execution timing starts in the worker, not at submit.
- Stale-cycle and quarantined-generation results are classified separately.

Result: **6 passed**.

## Decision Engine integrity

- Original SHA-256: `00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce`
- RC6.4.4 SHA-256: `00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce`
- Status: **UNCHANGED**

## Evidence classification

- **VERIFIED STRUCTURAL DEFECT:** previous implementation lacked an end-to-end guarantee that every `scan_coin()` future would complete.
- **PATCH VERIFIED BY CODE AUDIT AND ADVERSARIAL TESTS.**
- **PROBABLE HISTORICAL TRIGGER: UNCONFIRMED.**

The historical trigger must not be upgraded to `VERIFIED_CAUSAL_CHAIN` unless a future benchmark records the complete same-identity evidence chain.

## Remaining validation

The required two independent ≥3-hour functional benchmarks and stress benchmark were not run in this build container. They must be performed on the operational Windows/Binance environment under the frozen Performance Validation Standard.
