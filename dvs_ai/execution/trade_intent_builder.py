from __future__ import annotations

from dataclasses import dataclass

from dvs_ai.domain.models import CoinAnalysis, EntryStatus

from .models import ExecutionIntent, OrderSide, OrderType
from .position_sizer import RiskBasedPositionSizer


@dataclass(frozen=True)
class TradeIntentBuildResult:
    accepted: bool
    intent: ExecutionIntent | None
    reason: str
    quantity: float = 0.0
    risk_amount: float = 0.0
    notional: float = 0.0


class TradeIntentBuilder:
    """Converts an already-approved READY analysis into an execution intent."""

    def __init__(self, sizer: RiskBasedPositionSizer | None = None) -> None:
        self.sizer = sizer or RiskBasedPositionSizer()

    def build(
        self,
        analysis: CoinAnalysis,
        *,
        equity: float,
        risk_per_trade_pct: float,
        max_notional: float,
        leverage: int,
    ) -> TradeIntentBuildResult:
        if analysis.entry_status != EntryStatus.READY:
            return TradeIntentBuildResult(False, None, "NOT_READY")
        if analysis.footprint_gate != "READY_CANDIDATE":
            return TradeIntentBuildResult(False, None, "FOOTPRINT_GATE_BLOCK")
        if analysis.footprint_confirmation_depth != "STRONG":
            return TradeIntentBuildResult(False, None, "FOOTPRINT_NOT_STRONG")
        if analysis.footprint_direction_alignment != "ALIGNED":
            return TradeIntentBuildResult(False, None, "FOOTPRINT_NOT_ALIGNED")
        if not analysis.risk.liquidation_safe:
            return TradeIntentBuildResult(False, None, "LIQUIDATION_UNSAFE")

        plan = analysis.trade_plan
        entry = (plan.entry_low+plan.entry_high)/2.0
        sizing = self.sizer.size(
            equity=equity,
            risk_per_trade_pct=risk_per_trade_pct,
            entry_price=entry,
            invalidation=plan.invalidation,
            footprint_quality=analysis.footprint_score,
            rr=plan.rr_to_tp2,
            max_notional=max_notional,
        )
        if not sizing.valid:
            return TradeIntentBuildResult(
                False, None, sizing.reason
            )

        side = (
            OrderSide.BUY
            if analysis.direction == "LONG"
            else OrderSide.SELL
        )
        intent = ExecutionIntent(
            symbol=analysis.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=sizing.quantity,
            leverage=leverage,
            metadata={
                "source": "AUTO_PAPER_V1",
                "entry_reference": entry,
                "invalidation": plan.invalidation,
                "tp1": plan.tp1,
                "tp2": plan.tp2,
                "footprint_score": analysis.footprint_score,
                "position_building_score": analysis.position_building_score,
            },
        )
        return TradeIntentBuildResult(
            True,
            intent,
            "READY",
            quantity=sizing.quantity,
            risk_amount=sizing.risk_amount,
            notional=sizing.notional,
        )
