from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, ROUND_DOWN

from .models import ExecutionIntent, OrderType, ValidationResult


class OrderValidator:
    """Normalizes Binance symbol filters before any broker call."""

    @staticmethod
    def _floor(value: float, step: float) -> float:
        if step <= 0:
            return float(value)
        d_value = Decimal(str(value))
        d_step = Decimal(str(step))
        units = (d_value/d_step).to_integral_value(rounding=ROUND_DOWN)
        return float(units*d_step)

    def validate(
        self,
        intent: ExecutionIntent,
        filters: dict,
        mark_price: float,
    ) -> ValidationResult:
        reasons: list[str] = []
        step = float(filters.get("step_size", 0.0))
        tick = float(filters.get("tick_size", 0.0))
        min_qty = float(filters.get("min_qty", 0.0))
        min_notional = float(filters.get("min_notional", 0.0))
        max_leverage = int(filters.get("max_leverage", 125))

        quantity = self._floor(intent.quantity, step)
        price = intent.price
        stop_price = intent.stop_price
        if price is not None:
            price = self._floor(price, tick)
        if stop_price is not None:
            stop_price = self._floor(stop_price, tick)

        if quantity <= 0:
            reasons.append("QUANTITY_ZERO_AFTER_PRECISION")
        if quantity < min_qty:
            reasons.append(f"MIN_QTY:{quantity}<{min_qty}")
        effective_price = price or mark_price
        if quantity*max(effective_price, 0.0) < min_notional:
            reasons.append("MIN_NOTIONAL")
        if intent.leverage > max_leverage:
            reasons.append(f"LEVERAGE_LIMIT:{intent.leverage}>{max_leverage}")
        if intent.order_type == OrderType.LIMIT and (price is None or price <= 0):
            reasons.append("LIMIT_PRICE_REQUIRED")
        if intent.order_type in (
            OrderType.STOP_MARKET,
            OrderType.TAKE_PROFIT_MARKET,
        ) and (stop_price is None or stop_price <= 0):
            reasons.append("STOP_PRICE_REQUIRED")

        normalized = replace(
            intent,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            leverage=min(intent.leverage, max_leverage),
        )
        return ValidationResult(
            valid=not reasons,
            normalized_intent=normalized if not reasons else None,
            reasons=tuple(reasons),
        )
