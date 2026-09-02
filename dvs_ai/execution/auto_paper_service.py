from __future__ import annotations

from dataclasses import dataclass

from .execution_service import ExecutionService
from .models import ExecutionMode
from .position_reconciler import (
    PositionReconciler,
    ReconciliationResult,
)
from .position_tracker import PositionTracker
from .trade_intent_builder import (
    TradeIntentBuildResult,
    TradeIntentBuilder,
)


@dataclass(frozen=True)
class AutoPaperResult:
    build: TradeIntentBuildResult
    execution: object | None
    reconciliation: ReconciliationResult | None


class AutoPaperExecutionService:
    """
    PAPER-only automated execution boundary with tracking and reconciliation.

    TESTNET/LIVE are rejected in the constructor.
    """

    def __init__(
        self,
        execution_service: ExecutionService,
        *,
        tracker: PositionTracker | None = None,
        builder: TradeIntentBuilder | None = None,
        reconciler: PositionReconciler | None = None,
    ) -> None:
        if execution_service.mode != ExecutionMode.PAPER:
            raise ValueError("AUTO_PAPER_REQUIRES_PAPER_MODE")
        self.execution_service = execution_service
        self.builder = builder or TradeIntentBuilder()
        self.tracker = tracker or PositionTracker(
            "data/dvs_execution_positions.db"
        )
        self.reconciler = reconciler or PositionReconciler(
            self.tracker
        )

    def consider(
        self,
        analysis,
        *,
        equity: float,
        risk_per_trade_pct: float,
        max_notional: float,
        leverage: int,
        filters: dict,
        risk_metrics: dict,
        require_protective_stop: bool = True,
    ) -> AutoPaperResult:
        built = self.builder.build(
            analysis,
            equity=equity,
            risk_per_trade_pct=risk_per_trade_pct,
            max_notional=max_notional,
            leverage=leverage,
        )
        if not built.accepted or built.intent is None:
            return AutoPaperResult(built, None, None)

        execution = self.execution_service.execute(
            built.intent,
            filters=filters,
            mark_price=analysis.snapshot.last_price,
            risk_metrics=risk_metrics,
            user_confirmed=False,
        )
        if not execution.accepted:
            return AutoPaperResult(built, execution, None)

        # PAPER protective stop is represented by the immutable trade plan.
        reconciliation = self.reconciler.reconcile_fill(
            execution_result=execution,
            direction=analysis.direction,
            invalidation=analysis.trade_plan.invalidation,
            tp1=analysis.trade_plan.tp1,
            tp2=analysis.trade_plan.tp2,
            require_protective_stop=require_protective_stop,
            protective_stop_attached=True,
        )
        return AutoPaperResult(
            built,
            execution,
            reconciliation,
        )

    def update_positions(
        self,
        mark_prices: dict[str, float],
    ) -> list:
        updated = []
        for position in self.tracker.open_positions():
            mark = mark_prices.get(position.symbol)
            if mark is None:
                continue
            refreshed = self.tracker.update_mark(
                position.client_order_id,
                mark,
            )
            if refreshed is not None:
                updated.append(refreshed)
        return updated
