from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from ..decision import DecisionAction, ScientificDecision

class ShadowHorizon(str, Enum):
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"

@dataclass(frozen=True, slots=True)
class ShadowObservation:
    decision_id: str
    horizon: ShadowHorizon
    observed_at: datetime
    entry_price: float
    exit_price: float
    return_pct: float
    correct: bool

    @classmethod
    def from_prices(cls, decision: ScientificDecision, horizon: ShadowHorizon,
                    observed_at: datetime, entry_price: float, exit_price: float) -> "ShadowObservation":
        if entry_price <= 0 or exit_price <= 0:
            raise ValueError("prices must be positive")
        raw = (exit_price - entry_price) / entry_price
        signed = -raw if decision.final_action is DecisionAction.SELL else raw
        if decision.final_action in (DecisionAction.HOLD, DecisionAction.NO_ACTION):
            signed = 0.0
        return cls(decision.decision_id, horizon, observed_at, entry_price, exit_price,
                   signed * 100.0, signed > 0.0)

@dataclass(frozen=True, slots=True)
class ShadowMetrics:
    observations: int
    wins: int
    losses: int
    win_rate: float
    average_return_pct: float
    profit_factor: float
