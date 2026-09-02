from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .evidence import CONTRACT_VERSION
from .reason_codes import normalize_reason_codes


class CertificationStatus(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    NOT_EVALUATED = "NOT_EVALUATED"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class CertificationRecord:
    certification_id: str
    validation_id: str
    model_id: str
    model_version: str
    evaluated_at: str
    status: CertificationStatus
    expires_at: str = ""
    reason_codes: tuple[str, ...] = ()
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        required = (self.certification_id, self.validation_id, self.model_id, self.model_version)
        if not all(value.strip() for value in required):
            raise ValueError("certification, validation and model identifiers are required")
        object.__setattr__(self, "reason_codes", normalize_reason_codes(self.reason_codes))
