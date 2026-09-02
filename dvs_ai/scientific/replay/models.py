from __future__ import annotations

from dataclasses import dataclass

from ..contracts import ScientificLifecycleState


@dataclass(frozen=True, slots=True)
class ReplayResult:
    run_id: str
    valid: bool
    final_state: ScientificLifecycleState | None
    events_replayed: int
    reason_codes: tuple[str, ...] = ()
