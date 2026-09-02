# Runtime Gates Specification

## ModelEvaluationGate

Two report modes are frozen:

- `QUALIFYING_HOLDOUT_EVALUATION`: `qualifying=true`, start status `LOCKED_UNCONSUMED`, immutable consumption record required.
- `HISTORICAL_BENCHMARK_EVALUATION`: `qualifying=false`, `historical_benchmark_only=true`, start status `CONSUMED`.

The production implementation must use an atomic claim transaction equivalent to the previously verified `BEGIN IMMEDIATE` claim/TTL pattern. `HOLDOUT_ACCESS_STARTED` must be persisted before Test rows are exposed.

## ModelLifecycleGate

Promotion to `VALIDATED` must independently verify report mode, qualifying flag, start status, consumption record, model/split identity, and hashes. Historical reports are always rejected for promotion.

## Audit limitation

Direct out-of-band filesystem access cannot be technically prevented by these application gates. Such access is classified as `OUT_OF_BAND_HOLDOUT_ACCESS` and the affected Test must be treated as consumed.
