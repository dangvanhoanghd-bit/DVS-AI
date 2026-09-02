# Observable Universe Truth Audit — Alpha 2.32.1

## Verified claims
- Observability is computed from actual row intersections, never inferred from marginals.
- `FrozenObservableContext` is immutable and bound to threshold, filter and source snapshot hashes.
- `UNOBSERVABLE` and `OBSERVABLE_BUT_UNDERPOWERED` both hard-block recommendation.
- Threshold profile requires matching SHA-256 manifest, exact allowlist and guardrails.
- Threshold changes require an exact confirmation phrase, backup, atomic replacement and append-only audit event.
- Downstream protocol gate has no SQLite or repository dependency.

## Frozen Protocol v1.0 defaults
- Regime/direction/order-flow observable: 30
- Candidate eligible: 40
- Paired observable: 30
- Powered: 60
- Paired powered: 60

## Safety boundary
Observe-only. No Decision, Quantum, Promotion, Testnet or LIVE mutation.
