from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_position_notional: float = 2_000.0
    max_total_exposure: float = 5_000.0
    max_drawdown: float = 0.20
    max_daily_loss: float = 500.0
    max_leverage: float = 1.0

    def __post_init__(self) -> None:
        if min(self.max_position_notional, self.max_total_exposure, self.max_daily_loss, self.max_leverage) <= 0:
            raise ValueError("risk limits must be positive")
        if not 0 < self.max_drawdown < 1:
            raise ValueError("max_drawdown must be between 0 and 1")

@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    approved_quantity: float
    reason_codes: tuple[str, ...]
