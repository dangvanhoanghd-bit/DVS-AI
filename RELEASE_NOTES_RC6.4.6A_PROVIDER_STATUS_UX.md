# RC6.4.6A — Provider Status UX Hardening

## Scope
Presentation-layer hardening only. Provider circuit state machine, retry policy,
Decision Engine, and Scan Lifecycle are unchanged.

## Changes
- Added a live Provider badge: ONLINE / BACKOFF / PROBING.
- BACKOFF shows a human-readable countdown (seconds/minutes/hours).
- Circuit-open errors are translated into an operator-facing explanation.
- API Health avoids creating a redundant worker request while the circuit is
  known OPEN; it reports the remaining backoff immediately from MainThread
  without performing network I/O.
- Universe-load circuit failures now explain that Binance is temporarily
  limiting the IP and that the app does not need to be restarted.

## Runtime validation still required
- Confirm countdown decreases once per second.
- Confirm GUI remains responsive.
- Confirm no network request is emitted when API Health is clicked during OPEN.
- Confirm one HALF_OPEN probe and transition to CLOSED/OPEN from telemetry.
