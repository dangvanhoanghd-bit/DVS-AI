from __future__ import annotations

from enum import Enum


class ScientificLifecycleState(str, Enum):
    RAW = "RAW"
    FEATURED = "FEATURED"
    EVIDENCE_READY = "EVIDENCE_READY"
    VALIDATED = "VALIDATED"
    CERTIFIED = "CERTIFIED"
    REGISTERED = "REGISTERED"
    AVAILABLE = "AVAILABLE"
    FAILED = "FAILED"


_ALLOWED_TRANSITIONS: dict[ScientificLifecycleState, frozenset[ScientificLifecycleState]] = {
    ScientificLifecycleState.RAW: frozenset({ScientificLifecycleState.FEATURED, ScientificLifecycleState.FAILED}),
    ScientificLifecycleState.FEATURED: frozenset({ScientificLifecycleState.EVIDENCE_READY, ScientificLifecycleState.FAILED}),
    ScientificLifecycleState.EVIDENCE_READY: frozenset({ScientificLifecycleState.VALIDATED, ScientificLifecycleState.FAILED}),
    ScientificLifecycleState.VALIDATED: frozenset({ScientificLifecycleState.CERTIFIED, ScientificLifecycleState.FAILED}),
    ScientificLifecycleState.CERTIFIED: frozenset({ScientificLifecycleState.REGISTERED, ScientificLifecycleState.FAILED}),
    ScientificLifecycleState.REGISTERED: frozenset({ScientificLifecycleState.AVAILABLE, ScientificLifecycleState.FAILED}),
    ScientificLifecycleState.AVAILABLE: frozenset({ScientificLifecycleState.FAILED}),
    ScientificLifecycleState.FAILED: frozenset(),
}


def can_transition(current: ScientificLifecycleState, target: ScientificLifecycleState) -> bool:
    return target in _ALLOWED_TRANSITIONS[current]


def require_transition(current: ScientificLifecycleState, target: ScientificLifecycleState) -> None:
    if not can_transition(current, target):
        raise ValueError(f"invalid scientific lifecycle transition: {current.value} -> {target.value}")
