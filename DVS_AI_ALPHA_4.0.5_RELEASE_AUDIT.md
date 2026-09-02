# DVS AI Alpha 4.0.5 — Qualification Actionable Evidence Quality Gate

## Implemented

- Corrected qualification regime extraction to `analysis.regime.regime`.
- Corrected qualification phase extraction to `analysis.phase_summary`.
- Added frozen governance profile v2 with:
  - `minimum_actionable_count = 30`
  - `minimum_actionable_ratio = 0.05`
- Required actionable observations are calculated as:
  - `max(minimum_actionable_count, ceil(total_cycles * minimum_actionable_ratio))`
- Added `ACTIONABLE_EVIDENCE_INSUFFICIENT` qualification status.
- Prevented all-NO_ACTION agreement from reaching `READY_FOR_GOVERNANCE_REVIEW`.
- Added actionable count, ratio, required count, gap, and decision-agreement confidence metrics.
- Added `UNOBSERVABLE` semantics when there are zero actionable comparisons.
- Updated Scientific Report HTML/PDF/JSON and Qualification Dashboard status.
- Preserved Legacy Paper Authority, Unified Core SHADOW_ONLY, append-only evidence, SHA-256 sealing, and execution locks.

## Verification

- Targeted qualification/audit tests: 26 passed.
- Full regression suite: 689 passed, 0 failed.
