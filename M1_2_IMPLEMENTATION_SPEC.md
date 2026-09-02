# DVS AI Alpha — Milestone 1.2 Bridge Hardening

## Objective
Eliminate silent fallback from a configured scientific backend root to the packaged snapshot while preserving the observe-only, JSON-artifact boundary.

## Contract changes
`ScientificBackendStatus` now exposes:

- `backend_source`: `CONFIGURED_ROOT`, `PACKAGED_SNAPSHOT`, or `NONE`
- `configured_root`
- `active_root`
- `fallback_reason`
- `reason_codes`

## Fail-closed behavior
A configured-root failure can never be hidden. When a valid packaged snapshot is used instead, status is `DEGRADED` and includes both the configured-root failure code and `CONFIGURED_ROOT_FALLBACK_USED`.

No execution package is imported. No backend state is written. No trading, exchange, database, deployment, or LIVE boundary is changed.
