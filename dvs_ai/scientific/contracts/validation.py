from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .evidence import CONTRACT_VERSION
from .reason_codes import normalize_reason_codes


class ValidationStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"


class StabilityStatus(str, Enum):
    STABLE = "STABLE"
    UNSTABLE = "UNSTABLE"
    NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    validation_id: str
    evidence_id: str
    started_at: str
    completed_at: str
    status: ValidationStatus
    stability_status: StabilityStatus = StabilityStatus.NOT_EVALUATED
    metrics: tuple[tuple[str, float], ...] = ()
    reason_codes: tuple[str, ...] = ()
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.validation_id.strip() or not self.evidence_id.strip():
            raise ValueError("validation_id and evidence_id are required")
        names = [name for name, _ in self.metrics]
        if len(names) != len(set(names)):
            raise ValueError("validation metric names must be unique")
        object.__setattr__(self, "metrics", tuple((str(name), float(value)) for name, value in self.metrics))
        object.__setattr__(self, "reason_codes", normalize_reason_codes(self.reason_codes))
