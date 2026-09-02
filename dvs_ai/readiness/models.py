from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class DeploymentMode(str, Enum):
    SIMULATION_ONLY="SIMULATION_ONLY"; LIVE_ELIGIBLE="LIVE_ELIGIBLE"

@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    passed: bool
    detail: str = ""

@dataclass(frozen=True)
class ReadinessReport:
    mode: DeploymentMode
    checks: tuple[ReadinessCheck,...]
    reason_codes: tuple[str,...]
    @property
    def ready(self) -> bool:
        return self.mode is DeploymentMode.LIVE_ELIGIBLE
