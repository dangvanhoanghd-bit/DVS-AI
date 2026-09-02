# M6 Decision Integration, Shadow Validation and Reporting

Implemented simultaneously on the M5.4-M5.6 Scientific Core baseline.

## Added
- Read-only, fail-closed Decision Adapter
- Immutable decision contracts
- Shadow observations at 15m/1h/4h/1d horizons
- Aggregate win rate, average return and profit factor
- Scientific Decision Report backed by lifecycle explainability

## Safety boundary
No exchange order submission or live trading capability is included. Unauthorized, unavailable, low-confidence or unverifiable runs resolve to `NO_ACTION`.
