# DVS AI RC6.4.6 — Provider Global Circuit Breaker + Async API Health Check

## Scope

- RC6.4.5b: moved `/fapi/v1/time` health check off the Qt GUI MainThread.
- RC6.4.6: added a process-wide atomic circuit breaker for Binance HTTP 418/429.
- Decision Engine and scan scoring logic are unchanged.

## Circuit invariants

- One non-reentrant `threading.Lock` protects state and `blocked_until`.
- `OPEN -> HALF_OPEN` is an atomic claim.
- Exactly one half-open probe may perform network I/O.
- Other callers fail immediately with `PROVIDER_HALF_OPEN_PROBE_ALREADY_CLAIMED`.
- Concurrent 418/429 observations update `blocked_until` using `max(current, observed + retry_after_raw)`.
- The raw server Retry-After value controls the global half-open time; the local 30-second retry cap is not used for circuit scheduling.
- Requests rejected by the circuit are classified separately from coin-data errors.

## Telemetry

- `provider_circuit_opened`
- `provider_circuit_extended`
- `provider_request_short_circuited`
- `provider_circuit_half_open`
- `provider_half_open_probe_started`
- `provider_half_open_probe_finished`
- `provider_circuit_closed`
- `api_health_check_started`
- `api_health_check_finished`
- `api_health_check_failed`
- `api_health_check_late_result_discarded`

## Runtime status

Code audit and local adversarial tests pass. Windows runtime validation remains pending.
