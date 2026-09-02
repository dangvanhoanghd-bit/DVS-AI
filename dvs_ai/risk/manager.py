from __future__ import annotations
from datetime import datetime, timezone
from .models import RiskDecision, RiskLimits

class RiskManager:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()
        self._kill_switch = False
        self._day = datetime.now(timezone.utc).date()
        self._daily_realized_pnl = 0.0

    @property
    def kill_switch_enabled(self) -> bool:
        return self._kill_switch

    def enable_kill_switch(self) -> None:
        self._kill_switch = True

    def disable_kill_switch(self) -> None:
        self._kill_switch = False

    def record_realized_pnl(self, pnl: float, *, at: datetime | None = None) -> None:
        day = (at or datetime.now(timezone.utc)).date()
        if day != self._day:
            self._day, self._daily_realized_pnl = day, 0.0
        self._daily_realized_pnl += float(pnl)

    def evaluate(self, *, price: float, requested_quantity: float, current_exposure: float,
                 equity: float, drawdown: float) -> RiskDecision:
        codes: list[str] = []
        if price <= 0 or requested_quantity <= 0 or equity <= 0:
            return RiskDecision(False, 0.0, ("RISK_INVALID_INPUT",))
        if self._kill_switch:
            codes.append("RISK_KILL_SWITCH_ENABLED")
        if drawdown >= self.limits.max_drawdown:
            codes.append("RISK_MAX_DRAWDOWN_EXCEEDED")
        if self._daily_realized_pnl <= -self.limits.max_daily_loss:
            codes.append("RISK_DAILY_LOSS_LIMIT_EXCEEDED")
        max_notional = min(self.limits.max_position_notional,
                           max(0.0, self.limits.max_total_exposure - current_exposure),
                           equity * self.limits.max_leverage)
        approved = min(requested_quantity, max_notional / price)
        if approved <= 0:
            codes.append("RISK_EXPOSURE_LIMIT_EXCEEDED")
        if codes:
            return RiskDecision(False, 0.0, tuple(codes))
        if approved < requested_quantity:
            codes.append("RISK_QUANTITY_REDUCED")
        return RiskDecision(True, approved, tuple(codes))
