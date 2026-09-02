from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .evidence import CONTRACT_VERSION
from .reason_codes import normalize_reason_codes


class RegistryStatus(str, Enum):
    REGISTERED = "REGISTERED"
    NOT_REGISTERED = "NOT_REGISTERED"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    snapshot_id: str
    generated_at: str
    model_id: str
    model_version: str
    certification_id: str
    status: RegistryStatus
    maturity_level: str
    previous_snapshot_id: str = ""
    reason_codes: tuple[str, ...] = ()
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        required = (self.snapshot_id, self.model_id, self.model_version)
        if not all(value.strip() for value in required):
            raise ValueError("snapshot_id, model_id and model_version are required")
        if self.status is RegistryStatus.REGISTERED and not self.certification_id.strip():
            raise ValueError("registered models require a certification_id")
        object.__setattr__(self, "reason_codes", normalize_reason_codes(self.reason_codes))
