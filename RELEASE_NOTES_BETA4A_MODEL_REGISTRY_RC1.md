# Beta 4A M6 Model Registry RC1 — Release Notes

Status: **AUDIT_CANDIDATE**

## Added

- `dvs_ai.beta4a.model_registry.ModelRegistry`
- Immutable, SHA-256-sealed Model Slot manifests
- Immutable lifecycle transition records
- Derived and rebuildable `model_slot_current` index
- Frozen legal states: EMPTY, RESERVED, TRAINING, TRAINED_UNVALIDATED, VALIDATED, REJECTED
- Generic transitions for pre-validation lifecycle and rejection
- Explicit hard block preventing direct transition to VALIDATED; validation remains exclusive to `ModelLifecycleGate`
- Audit snapshot support

## Governance behavior

The registry is an artifact store plus a derived index. The current-state table is not primary truth and can be rebuilt from immutable transition history.

## Scope boundary

This release completes the Beta 4A data-preparation and governance foundation. It does not train an ML model and does not claim Beta 4B functionality.
