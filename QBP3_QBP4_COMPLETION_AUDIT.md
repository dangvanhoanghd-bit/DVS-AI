# QBP-3 / QBP-4 Completion Audit

## Scope

This release adds observe-only research validation and governance review infrastructure above QBP-2.

### QBP-3
- Deterministic percentile bootstrap for mean realized-R.
- Chronological stability windows with explicit warnings.
- Holm-Bonferroni family-wise multiple-comparison control.
- Capability lock below 300 qualified outcomes.

### QBP-4
- Review eligibility lock below 500 qualified outcomes.
- Evidence checklist and deterministic evidence digest.
- Mandatory external human governance sign-off.
- Paper authority is never granted by code.
- Production and execution authority remain false.

## Safety invariants

The frozen Decision Engine is not modified. QBP-3 and QBP-4 are research/governance services only.
