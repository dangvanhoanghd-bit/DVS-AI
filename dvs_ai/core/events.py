from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Immutable event envelope shared by the unified runtime."""

    name: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("event name is required")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
