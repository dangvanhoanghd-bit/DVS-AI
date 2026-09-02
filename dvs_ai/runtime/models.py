from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping

class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"

@dataclass(frozen=True)
class ComponentHealth:
    name: str
    status: HealthStatus
    message: str = ""
    metrics: Mapping[str, float] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))

@dataclass(frozen=True)
class HealthReport:
    status: HealthStatus
    components: tuple[ComponentHealth, ...]
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
