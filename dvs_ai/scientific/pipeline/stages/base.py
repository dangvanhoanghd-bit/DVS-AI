from __future__ import annotations

from typing import Protocol

from ...contracts import CertificationRecord, EvidenceDelta, EvidenceRecord, RegistrySnapshot, ValidationResult


class EvidenceDeltaStage(Protocol):
    def __call__(self, evidence: EvidenceRecord) -> EvidenceDelta: ...


class ValidationStage(Protocol):
    def __call__(self, evidence: EvidenceRecord, delta: EvidenceDelta) -> ValidationResult: ...


class StabilityStage(Protocol):
    def __call__(self, validation: ValidationResult) -> ValidationResult: ...


class CertificationStage(Protocol):
    def __call__(self, validation: ValidationResult) -> CertificationRecord: ...


class RegistryStage(Protocol):
    def __call__(self, certification: CertificationRecord) -> RegistrySnapshot: ...
