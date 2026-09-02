from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..contracts import (
    CertificationRecord,
    EvidenceDelta,
    EvidenceRecord,
    RegistrySnapshot,
    ScientificLifecycleState,
    ValidationResult,
    normalize_reason_codes,
)


@dataclass(frozen=True, slots=True)
class PipelineEvent:
    stage: str
    state: ScientificLifecycleState
    succeeded: bool
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_codes", normalize_reason_codes(self.reason_codes))


@dataclass(frozen=True, slots=True)
class ScientificPipelineResult:
    run_id: str
    state: ScientificLifecycleState
    evidence: EvidenceRecord
    evidence_delta: Optional[EvidenceDelta] = None
    validation: Optional[ValidationResult] = None
    certification: Optional[CertificationRecord] = None
    registry_snapshot: Optional[RegistrySnapshot] = None
    events: tuple[PipelineEvent, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id is required")
        object.__setattr__(self, "reason_codes", normalize_reason_codes(self.reason_codes))

    @property
    def succeeded(self) -> bool:
        return self.state is ScientificLifecycleState.AVAILABLE
