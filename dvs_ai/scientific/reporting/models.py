from __future__ import annotations
from dataclasses import dataclass
from ..decision import ScientificDecision

@dataclass(frozen=True, slots=True)
class ScientificDecisionReport:
    decision: ScientificDecision
    lifecycle_integrity_verified: bool
    lifecycle_event_count: int
    lifecycle_summary: str
    primary_reason_codes: tuple[str, ...]
