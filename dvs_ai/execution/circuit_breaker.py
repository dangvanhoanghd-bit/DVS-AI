from __future__ import annotations

from .models import CircuitBreakerState


class ExecutionCircuitBreaker:
    """Hard gate for opening new risk. Reduce-only exits remain allowed."""

    def __init__(
        self,
        daily_loss_limit: float = 50.0,
        max_consecutive_losses: int = 4,
        max_open_exposure: float = 5000.0,
        max_daily_trades: int = 30,
        max_api_error_rate: float = 0.25,
        max_market_data_age_seconds: float = 15.0,
    ) -> None:
        self.daily_loss_limit = abs(float(daily_loss_limit))
        self.max_consecutive_losses = max(1, int(max_consecutive_losses))
        self.max_open_exposure = max(0.0, float(max_open_exposure))
        self.max_daily_trades = max(1, int(max_daily_trades))
        self.max_api_error_rate = max(0.0, min(1.0, float(max_api_error_rate)))
        self.max_market_data_age_seconds = max(1.0, float(max_market_data_age_seconds))
        self.manual_kill_switch = False

    def evaluate(
        self,
        *,
        daily_pnl: float,
        consecutive_losses: int,
        open_exposure: float,
        daily_trades: int,
        api_error_rate: float,
        market_data_age_seconds: float,
    ) -> CircuitBreakerState:
        reasons: list[str] = []
        if self.manual_kill_switch:
            reasons.append("MANUAL_KILL_SWITCH")
        if daily_pnl <= -self.daily_loss_limit:
            reasons.append("DAILY_LOSS_LIMIT")
        if consecutive_losses >= self.max_consecutive_losses:
            reasons.append("MAX_CONSECUTIVE_LOSSES")
        if open_exposure >= self.max_open_exposure:
            reasons.append("MAX_OPEN_EXPOSURE")
        if daily_trades >= self.max_daily_trades:
            reasons.append("MAX_DAILY_TRADES")
        if api_error_rate >= self.max_api_error_rate:
            reasons.append("HIGH_API_ERROR_RATE")
        if market_data_age_seconds >= self.max_market_data_age_seconds:
            reasons.append("STALE_MARKET_DATA")
        return CircuitBreakerState(
            blocked=bool(reasons),
            reasons=tuple(reasons),
            daily_pnl=float(daily_pnl),
            consecutive_losses=int(consecutive_losses),
            open_exposure=float(open_exposure),
            daily_trades=int(daily_trades),
            api_error_rate=float(api_error_rate),
            market_data_age_seconds=float(market_data_age_seconds),
        )
