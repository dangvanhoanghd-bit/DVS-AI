from __future__ import annotations

from dataclasses import dataclass

from dvs_ai.core import DomainEvent, EventBus
from dvs_ai.monitoring import Alert, AlertCenter, AlertSeverity
from dvs_ai.runtime import RuntimeHealthMonitor
from dvs_ai.strategy_intelligence import StrategyDecisionBridge, StrategyIntelligenceEngine
from dvs_ai.trading import OrderStatus, PaperTradingEngine

from .models import UnifiedCycleRequest, UnifiedCycleResult


@dataclass(slots=True)
class DVSAICore:
    """Unified application kernel joining the M1-M9 runtime boundary.

    Upstream M1-M4 components supply a normalized MarketSnapshot and a
    scientific pipeline run id. M5 ledger integrity authorizes M6 decisions;
    M9 creates the fused signal; M7 risk/paper execution applies the action;
    M8 health and alerts observe the full cycle.
    """

    strategy_engine: StrategyIntelligenceEngine
    decision_bridge: StrategyDecisionBridge
    paper_engine: PaperTradingEngine
    event_bus: EventBus
    health_monitor: RuntimeHealthMonitor
    alerts: AlertCenter

    def run_cycle(self, request: UnifiedCycleRequest) -> UnifiedCycleResult:
        emitted: list[str] = []

        def emit(name: str, **payload: object) -> None:
            emitted.append(name)
            failures = self.event_bus.publish(DomainEvent(name, payload))
            if failures:
                self.alerts.publish(Alert(
                    severity=AlertSeverity.WARNING,
                    code="EVENT_HANDLER_FAILURE",
                    message=f"{len(failures)} handler(s) failed for {name}",
                    source="DVSAICore",
                ))

        emit("market.snapshot.accepted", symbol=request.snapshot.symbol,
             timeframe=request.snapshot.timeframe, pipeline_run_id=request.pipeline_run_id)
        self.health_monitor.heartbeat("unified_core")

        fused = self.strategy_engine.evaluate(request.snapshot)
        emit("strategy.signal.fused", direction=fused.direction.value,
             confidence=fused.confidence, regime=fused.regime.value)

        decision = self.decision_bridge.authorize(
            pipeline_run_id=request.pipeline_run_id,
            snapshot=request.snapshot,
            fused_signal=fused,
        )
        emit("scientific.decision.created", action=decision.final_action.value,
             authorized=decision.authorized, reason_codes=decision.reason_codes)

        order = self.paper_engine.execute_decision(
            decision,
            price=request.snapshot.close,
            quantity=request.quantity,
            at=request.snapshot.observed_at,
        )
        emit("paper.order.completed", status=order.status.value,
             symbol=order.symbol, reason_codes=order.reason_codes)

        succeeded = order.status is OrderStatus.FILLED
        if not succeeded:
            self.alerts.publish(Alert(
                severity=AlertSeverity.WARNING,
                code="UNIFIED_CYCLE_NOT_EXECUTED",
                message="Unified cycle ended without a filled paper order",
                source="DVSAICore",
                context={"symbol": request.snapshot.symbol, "reason_codes": ",".join(order.reason_codes)},
            ))
        return UnifiedCycleResult(request, fused, decision, order, tuple(emitted), succeeded)
