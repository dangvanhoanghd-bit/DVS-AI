from datetime import datetime, timezone

from dvs_ai.application import DVSAICore, UnifiedCycleRequest
from dvs_ai.core import EventBus
from dvs_ai.monitoring import AlertCenter
from dvs_ai.risk import RiskLimits, RiskManager
from dvs_ai.runtime import RuntimeHealthMonitor
from dvs_ai.scientific.contracts import ScientificLifecycleState
from dvs_ai.scientific.decision import DecisionAdapter
from dvs_ai.scientific.ledger import InMemoryLedgerStorage, ScientificLedger
from dvs_ai.strategy_intelligence import (
    MarketRegime,
    MarketSnapshot,
    SignalDirection,
    StrategyDecisionBridge,
    StrategyIntelligenceEngine,
    StrategyRegistry,
    StrategySignal,
)
from dvs_ai.trading import OrderStatus, PaperPortfolio, PaperTradingEngine


class AlwaysLong:
    strategy_id = "always-long"
    version = "1.0"
    supported_regimes = frozenset(MarketRegime)

    def evaluate(self, snapshot):
        return StrategySignal(self.strategy_id, SignalDirection.LONG, 0.92, ("TEST_LONG",))


def available_ledger(run_id: str) -> ScientificLedger:
    ledger = ScientificLedger(InMemoryLedgerStorage())
    states = [
        ScientificLifecycleState.RAW,
        ScientificLifecycleState.FEATURED,
        ScientificLifecycleState.EVIDENCE_READY,
        ScientificLifecycleState.VALIDATED,
        ScientificLifecycleState.CERTIFIED,
        ScientificLifecycleState.REGISTERED,
        ScientificLifecycleState.AVAILABLE,
    ]
    for index, (before, after) in enumerate(zip(states, states[1:])):
        ledger.append_transition(
            pipeline_run_id=run_id,
            stage=f"stage-{index}",
            state_before=before,
            state_after=after,
            succeeded=True,
        )
    return ledger


def build_core(run_id: str) -> DVSAICore:
    registry = StrategyRegistry()
    registry.register(AlwaysLong())
    ledger = available_ledger(run_id)
    paper = PaperTradingEngine(
        PaperPortfolio(starting_balance=10_000.0),
        RiskManager(RiskLimits(max_position_notional=2_000.0, max_total_exposure=5_000.0, max_leverage=2.0)),
    )
    return DVSAICore(
        strategy_engine=StrategyIntelligenceEngine(registry),
        decision_bridge=StrategyDecisionBridge(DecisionAdapter(ledger, minimum_confidence=0.60)),
        paper_engine=paper,
        event_bus=EventBus(),
        health_monitor=RuntimeHealthMonitor(),
        alerts=AlertCenter(),
    )


def test_m1_to_m9_unified_happy_path_reaches_paper_execution():
    run_id = "run-unified-happy"
    core = build_core(run_id)
    observed = []
    core.event_bus.subscribe("*", lambda event: observed.append(event.name))
    snapshot = MarketSnapshot("BTCUSDT", "15m", 100.0, {"rsi": 52.0}, datetime.now(timezone.utc))

    result = core.run_cycle(UnifiedCycleRequest(run_id, snapshot, quantity=5.0))

    assert result.succeeded is True
    assert result.decision.authorized is True
    assert result.order.status is OrderStatus.FILLED
    assert observed == list(result.event_names)
    assert result.event_names == (
        "market.snapshot.accepted",
        "strategy.signal.fused",
        "scientific.decision.created",
        "paper.order.completed",
    )
    assert "BTCUSDT" in core.paper_engine.portfolio.positions


def test_unified_core_fails_closed_when_scientific_run_is_missing():
    run_id = "run-known"
    core = build_core(run_id)
    snapshot = MarketSnapshot("ETHUSDT", "1h", 2000.0, {"rsi": 60.0})

    result = core.run_cycle(UnifiedCycleRequest("run-missing", snapshot, quantity=0.1))

    assert result.succeeded is False
    assert result.decision.authorized is False
    assert result.order.status is OrderStatus.REJECTED
    assert "DECISION_SCIENTIFIC_RUN_NOT_AVAILABLE" in result.decision.reason_codes
    assert core.alerts.history(code="UNIFIED_CYCLE_NOT_EXECUTED")


def test_event_handler_failure_is_isolated_and_alerted():
    run_id = "run-handler-failure"
    core = build_core(run_id)
    core.event_bus.subscribe("strategy.signal.fused", lambda event: (_ for _ in ()).throw(RuntimeError("boom")))
    snapshot = MarketSnapshot("SOLUSDT", "15m", 150.0)

    result = core.run_cycle(UnifiedCycleRequest(run_id, snapshot, quantity=1.0))

    assert result.succeeded is True
    assert core.alerts.history(code="EVENT_HANDLER_FAILURE")
