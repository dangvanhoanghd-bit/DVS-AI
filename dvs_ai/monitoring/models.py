from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping

class AlertSeverity(str, Enum):
    INFO="INFO"; WARNING="WARNING"; ERROR="ERROR"; CRITICAL="CRITICAL"

@dataclass(frozen=True)
class Alert:
    code: str
    severity: AlertSeverity
    message: str
    source: str
    context: Mapping[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    def __post_init__(self) -> None:
        if not self.code or not self.source:
            raise ValueError("alert code and source are required")
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))
