from __future__ import annotations

from dataclasses import dataclass

from .evidence import CONTRACT_VERSION
from .reason_codes import normalize_reason_codes


@dataclass(frozen=True, slots=True)
class ExplainabilityTrace:
    trace_id: str
    decision_id: str
    generated_at: str
    evidence_ids: tuple[str, ...]
    validation_id: str
    certification_id: str
    registry_snapshot_id: str
    reason_codes: tuple[str, ...] = ()
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.trace_id.strip() or not self.decision_id.strip():
            raise ValueError("trace_id and decision_id are required")
        object.__setattr__(self, "evidence_ids", tuple(dict.fromkeys(self.evidence_ids)))
        object.__setattr__(self, "reason_codes", normalize_reason_codes(self.reason_codes))

    @property
    def is_complete(self) -> bool:
        return bool(
            self.evidence_ids
            and self.validation_id.strip()
            and self.certification_id.strip()
            and self.registry_snapshot_id.strip()
        )
