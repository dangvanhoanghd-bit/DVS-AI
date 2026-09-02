from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any

class ObservableState(str, Enum):
    UNOBSERVABLE = "UNOBSERVABLE"
    OBSERVABLE_BUT_UNDERPOWERED = "OBSERVABLE_BUT_UNDERPOWERED"
    OBSERVABLE = "OBSERVABLE"

class PowerState(str, Enum):
    UNPOWERED = "UNPOWERED"
    POWERED = "POWERED"

@dataclass(frozen=True)
class ObservableFilters:
    regime: str | None = None
    direction: str | None = None
    variant: str | None = None
    order_flow_quality: str | None = None
    candidate_id: str | None = None

    def normalized(self) -> "ObservableFilters":
        def n(v): return str(v).strip().upper() if v not in (None, "") else None
        return ObservableFilters(n(self.regime), n(self.direction), n(self.variant), n(self.order_flow_quality), str(self.candidate_id).strip() if self.candidate_id else None)

@dataclass(frozen=True)
class FrozenObservation:
    observation_id: int
    created_at: str
    candidate_id: str
    symbol: str
    direction: str
    regime: str
    variant: str
    order_flow_quality: str
    selected: bool
    outcome_r: float | None

@dataclass(frozen=True)
class FrozenObservableContext:
    context_id: str
    protocol_version: str
    threshold_profile_hash: str
    filters: ObservableFilters
    observations: tuple[FrozenObservation, ...]
    observation_ids: tuple[int, ...]
    sample_count: int
    paired_sample_count: int
    observability_state: ObservableState
    power_state: PowerState
    source_snapshot_hash: str
    artifact_hash: str

@dataclass(frozen=True)
class RecommendationGateResult:
    state: str
    reason: str
    allowed: bool
