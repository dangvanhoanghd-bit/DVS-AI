# Actionable Semantics Truth Audit — Alpha 2.32.5-r1

## Defect

`RecommendationMapper` returned `actionable=False` for every successful mapping, including
`READY_FOR_MANUAL_REVIEW` and `REVIEW_REQUIRED`. This did not enable unsafe execution, but made
the field semantically useless and allowed UI/API consumers to misrepresent human-review work.

## Fix

- `SUPPORTED` and `UNSUPPORTED` now map to `actionable=True`.
- `NO_ACTIONABLE_ISSUE_DETECTED`, non-powered states, and aborted/skipped states remain false.
- `EvidenceProtocolEnforcer` now checks both directions of the invariant:
  - manual review / review required must be actionable;
  - continue paper must not be actionable.

## Safety boundary

No automated action is introduced. `actionable=True` means human attention is required only.
Testnet and LIVE execution remain disabled.
