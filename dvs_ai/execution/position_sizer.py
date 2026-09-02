from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PositionSizingResult:
    valid: bool
    quantity: float
    risk_amount: float
    notional: float
    reason: str = ""


class RiskBasedPositionSizer:
    """Risk amount is fixed by equity and stop distance; leverage never raises loss."""

    def size(
        self,
        *,
        equity: float,
        risk_per_trade_pct: float,
        entry_price: float,
        invalidation: float,
        footprint_quality: float,
        rr: float,
        max_notional: float,
    ) -> PositionSizingResult:
        stop_distance = abs(float(entry_price)-float(invalidation))
        if equity <= 0 or stop_distance <= 0 or entry_price <= 0:
            return PositionSizingResult(False, 0.0, 0.0, 0.0, "INVALID_INPUT")

        quality_multiplier = (
            1.0 if footprint_quality >= 75 and rr >= 1.8
            else 0.8 if footprint_quality >= 62 and rr >= 1.5
            else 0.5
        )
        base_risk = float(equity)*max(0.0, float(risk_per_trade_pct))/100.0
        risk_amount = base_risk*quality_multiplier
        quantity = risk_amount/stop_distance
        notional = quantity*entry_price

        if max_notional > 0 and notional > max_notional:
            scale = max_notional/notional
            quantity *= scale
            risk_amount *= scale
            notional = max_notional

        return PositionSizingResult(
            valid=quantity > 0,
            quantity=quantity,
            risk_amount=risk_amount,
            notional=notional,
            reason="OK" if quantity > 0 else "ZERO_QUANTITY",
        )
