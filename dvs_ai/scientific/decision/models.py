from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping

class DecisionAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    NO_ACTION = "NO_ACTION"

@dataclass(frozen=True, slots=True)
class DecisionRequest:
    pipeline_run_id: str
    symbol: str
    proposed_action: DecisionAction
    confidence: float
    model_id: str
    features: Mapping[str, float] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.pipeline_run_id.strip() or not self.symbol.strip() or not self.model_id.strip():
            raise ValueError("pipeline_run_id, symbol and model_id are required")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "symbol", self.symbol.upper().strip())
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))

@dataclass(frozen=True, slots=True)
class ScientificDecision:
    decision_id: str
    pipeline_run_id: str
    symbol: str
    proposed_action: DecisionAction
    final_action: DecisionAction
    confidence: float
    authorized: bool
    reason_codes: tuple[str, ...]
    model_id: str
    created_at: datetime
