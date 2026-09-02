# M5.1 Implementation Notes

The new scientific package is deliberately dependency-light and independent from the existing GUI integration bridge. It creates a stable contract boundary before pipeline wiring.

Important invariants:
1. All records are frozen dataclasses with slots.
2. Metadata mappings are copied and exposed through a read-only mapping proxy.
3. Reason codes are normalized, de-duplicated and never invented by the normalizer.
4. `EvidenceDelta.meaningful=True` is invalid unless `hard_gates_passed=True`.
5. Validation metric names must be unique.
6. `RegistryStatus.REGISTERED` requires a certification ID.
7. Lifecycle transitions cannot skip scientific stages.

This sprint does not yet modify existing Decision Engine, Bridge, GUI, Paper Trade or runtime behavior.
