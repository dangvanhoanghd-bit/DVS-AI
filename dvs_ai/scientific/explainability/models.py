from __future__ import annotations

from dataclasses import dataclass

from ..contracts import ScientificLifecycleState


@dataclass(frozen=True, slots=True)
class ExplanationStep:
    sequence: int
    stage: str
    state_before: ScientificLifecycleState
    state_after: ScientificLifecycleState
    succeeded: bool
    reason_codes: tuple[str, ...]
    narrative: str


@dataclass(frozen=True, slots=True)
class ScientificExplanation:
    run_id: str
    final_state: ScientificLifecycleState
    succeeded: bool
    integrity_verified: bool
    steps: tuple[ExplanationStep, ...]
    primary_reason_codes: tuple[str, ...]
    summary: str
