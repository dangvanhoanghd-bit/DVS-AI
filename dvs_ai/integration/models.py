from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class BackendAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class BackendSource(str, Enum):
    CONFIGURED_ROOT = "CONFIGURED_ROOT"
    PACKAGED_SNAPSHOT = "PACKAGED_SNAPSHOT"
    NONE = "NONE"


class ScientificDataState(str, Enum):
    VALID = "VALID"
    STALE = "STALE"
    NOT_READY = "NOT_READY"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class SafetyBoundary:
    testnet: str
    deployment: str
    live: str
    enforcement: str
    scope: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SafetyBoundary":
        return cls(
            testnet=str(payload.get("testnet", "UNKNOWN")).upper(),
            deployment=str(payload.get("deployment", "UNKNOWN")).upper(),
            live=str(payload.get("live", "UNKNOWN")).upper(),
            enforcement=str(payload.get("enforcement", "UNKNOWN")).upper(),
            scope=str(payload.get("scope", "UNKNOWN")),
        )


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    state: ScientificDataState
    validation_status: str = "UNAVAILABLE"
    last_validation_at: str = ""
    validation_count: int = 0
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceSummary:
    state: ScientificDataState
    evidence_status: str = "UNAVAILABLE"
    evidence_count: int = 0
    last_evidence_at: str = ""
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReadinessSummary:
    state: ScientificDataState
    readiness_level: str = "UNAVAILABLE"
    readiness_score: float | None = None
    recommendation: str = ""
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CertificationSummary:
    state: ScientificDataState
    certification_status: str = "UNAVAILABLE"
    certificate_id: str = ""
    certified_at: str = ""
    reason_codes: tuple[str, ...] = ()




@dataclass(frozen=True, slots=True)
class ExplainabilitySummary:
    state: ScientificDataState
    status: str = "UNAVAILABLE"
    decision_id: str = ""
    generated_at: str = ""
    decision_type: str = ""
    confidence: float | None = None
    reason_codes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    validation_ref: str = ""
    model_version: str = ""


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    state: ScientificDataState
    decision_id: str = ""
    stages: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelVersionSummary:
    model_id: str
    version: str
    training_timestamp: str = ""
    registry_status: str = "UNAVAILABLE"
    maturity_level: str = "UNAVAILABLE"
    certified: bool = False
    certificate_id: str = ""
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelRegistrySummary:
    state: ScientificDataState
    registry_status: str = "UNAVAILABLE"
    current_model: ModelVersionSummary | None = None
    model_history: tuple[ModelVersionSummary, ...] = ()
    generated_at: str = ""
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScientificSummary:
    validation: ValidationSummary
    evidence: EvidenceSummary
    readiness: ReadinessSummary
    certification: CertificationSummary
    explainability: ExplainabilitySummary
    decision_trace: DecisionTrace
    registry: ModelRegistrySummary


@dataclass(frozen=True, slots=True)
class ScientificBackendStatus:
    engine_name: str
    engine_version: str
    availability: BackendAvailability
    build_valid: bool
    compile_passed: bool
    tests_run: int
    tests_successful: bool
    cli_help_available: bool
    safety: SafetyBoundary
    integration_mode: str
    source_path: str
    backend_source: BackendSource = BackendSource.NONE
    configured_root: str = ""
    active_root: str = ""
    fallback_reason: str = ""
    reason_codes: tuple[str, ...] = ()

    @property
    def display_state(self) -> str:
        if self.availability is BackendAvailability.UNAVAILABLE:
            return "UNAVAILABLE"
        if self.availability is BackendAvailability.DEGRADED:
            return "DEGRADED"
        if not self.build_valid or not self.tests_successful:
            return "DEGRADED"
        if self.safety.enforcement != "FAIL_CLOSED":
            return "DEGRADED"
        return "VERIFIED"

    @property
    def safe_for_observation(self) -> bool:
        return (
            self.display_state == "VERIFIED"
            and self.safety.live == "NOT_AUTHORIZED"
            and self.safety.deployment == "DISCONNECTED"
        )
