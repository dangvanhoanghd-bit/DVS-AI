from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import ModelSlotManifest, ModelSlotState
from .model_lifecycle_gate import ModelLifecycleGate
from .model_registry import ModelRegistry


@dataclass(frozen=True, slots=True)
class EffectiveModelState:
    model_slot_id: str
    state: ModelSlotState
    source: str
    registry_manifest: ModelSlotManifest | None
    lifecycle_transition: dict[str, Any] | None


def resolve_effective_model_state(
    *, model_slot_id: str, registry: ModelRegistry, lifecycle_gate: ModelLifecycleGate
) -> EffectiveModelState:
    """Read-only merged projection. Lifecycle VALIDATED evidence always wins."""
    registry_manifest = registry.get_current(model_slot_id)
    snapshot = lifecycle_gate.audit_snapshot(model_slot_id)
    validated = next(
        (row for row in reversed(snapshot["transitions"]) if row["target_state"] == ModelSlotState.VALIDATED.value),
        None,
    )
    if validated is not None:
        return EffectiveModelState(
            model_slot_id=model_slot_id,
            state=ModelSlotState.VALIDATED,
            source="MODEL_LIFECYCLE_GATE",
            registry_manifest=registry_manifest,
            lifecycle_transition=validated,
        )
    if registry_manifest is None:
        return EffectiveModelState(model_slot_id, ModelSlotState.EMPTY, "ABSENT", None, None)
    return EffectiveModelState(
        model_slot_id=model_slot_id,
        state=registry_manifest.state,
        source="MODEL_REGISTRY",
        registry_manifest=registry_manifest,
        lifecycle_transition=None,
    )
