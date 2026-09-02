from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from .reason_codes import normalize_reason_codes


CONTRACT_VERSION = "1.0"


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    observed_at: str
    source: str
    dataset_fingerprint: str
    sample_size: int
    time_coverage_seconds: int
    quality_score: float
    regimes: tuple[str, ...] = ()
    directions: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id is required")
        if not self.dataset_fingerprint.strip():
            raise ValueError("dataset_fingerprint is required")
        if self.sample_size < 0 or self.time_coverage_seconds < 0:
            raise ValueError("sample_size and time_coverage_seconds must be non-negative")
        if not 0.0 <= float(self.quality_score) <= 1.0:
            raise ValueError("quality_score must be within [0, 1]")
        object.__setattr__(self, "regimes", tuple(dict.fromkeys(map(str, self.regimes))))
        object.__setattr__(self, "directions", tuple(dict.fromkeys(map(str, self.directions))))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        object.__setattr__(self, "reason_codes", normalize_reason_codes(self.reason_codes))


@dataclass(frozen=True, slots=True)
class EvidenceDelta:
    current_evidence_id: str
    baseline_evidence_ids: tuple[str, ...]
    fingerprint_changed: bool
    sample_delta: int
    time_coverage_delta_seconds: int
    regime_delta: tuple[str, ...] = ()
    direction_delta: tuple[str, ...] = ()
    quality_delta: float = 0.0
    hard_gates_passed: bool = False
    meaningful: bool = False
    qualitative_score: float | None = None
    reason_codes: tuple[str, ...] = ()
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.current_evidence_id.strip():
            raise ValueError("current_evidence_id is required")
        if self.qualitative_score is not None and not 0.0 <= float(self.qualitative_score) <= 1.0:
            raise ValueError("qualitative_score must be within [0, 1]")
        if self.meaningful and not self.hard_gates_passed:
            raise ValueError("meaningful evidence requires all hard gates to pass")
        object.__setattr__(self, "baseline_evidence_ids", tuple(dict.fromkeys(self.baseline_evidence_ids)))
        object.__setattr__(self, "regime_delta", tuple(dict.fromkeys(self.regime_delta)))
        object.__setattr__(self, "direction_delta", tuple(dict.fromkeys(self.direction_delta)))
        object.__setattr__(self, "reason_codes", normalize_reason_codes(self.reason_codes))
