# DVS AI Alpha 2.21.1 — Hard Gate Invariant Audit

## Critical invariant restored

`apply_footprint_v31()` executes after `combine()`. It must therefore inherit
all non-compensable gates already applied by `combine()`.

The following conditions now always force final WAIT:

- `direction_confirmation_gate == "BLOCK"`
- `alignment.label == "MÂU THUẪN"`
- `regime.regime == "TRANSITION"`
- `maturity_gate == "EXHAUSTION"`
- `entry_status == RUNNING` due to an already-extended trend

A strong Footprint can no longer resurrect these cases to READY.

`maturity_gate == "LATE"` remains a proportional downgrade: READY is capped
to SETUP, matching the original combine() severity.

A fully healthy signal remains capable of reaching READY.
