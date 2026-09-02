from __future__ import annotations

"""Isolated Unified Core runtime used only for GUI shadow comparison.

This module owns an in-memory scientific ledger and paper portfolio.  It never
receives the application's PaperTradeService, exchange provider, or execution
credentials.  Its output is therefore observational and disposable.
"""

from dataclasses import dataclass
from typing import Mapping

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
    SignalDirection,
    StrategyDecisionBridge,
    StrategyIntelligenceEngine,
    StrategyRegistry,
    StrategySignal,
)
from dvs_ai.trading import PaperPortfolio, PaperTradingEngine


class GuiAnalysisStrategy:
    """Read-only bridge from normalized GUI snapshot features to M9 signal."""

    strategy_id = "gui-analysis-shadow"
    version = "1.0"
    supported_regimes = frozenset(MarketRegime)

    def evaluate(self, snapshot):
        features: Mapping[str, float] = snapshot.features
        long_score = float(features.get("legacy_long_score", 0.0))
        short_score = float(features.get("legacy_short_score", 0.0))
        confidence = max(0.0, min(1.0, float(features.get("legacy_confidence", 0.0))))
        if abs(long_score - short_score) < 5.0:
            direction = SignalDirection.NEUTRAL
            reason = "GUI_SHADOW_BALANCED_SCORES"
        elif long_score > short_score:
            direction = SignalDirection.LONG
            reason = "GUI_SHADOW_LONG_SCORE_DOMINANT"
        else:
            direction = SignalDirection.SHORT
            reason = "GUI_SHADOW_SHORT_SCORE_DOMINANT"
        return StrategySignal(
            self.strategy_id,
            direction,
            confidence,
            (reason, "GUI_SHADOW_OBSERVE_ONLY"),
        )


@dataclass(slots=True)
class GuiShadowCoreRuntime:
    """Sequential shadow runtime with synthetic, explicitly marked lifecycle."""

    core: DVSAICore
    ledger: ScientificLedger
    _prepared_runs: set[str]
    _release_run_total: int = 0
    _discard_run_total: int = 0
    _discarded_ledger_events_total: int = 0
    _paper_orders_cleared_total: int = 0

    def run_cycle(self, request: UnifiedCycleRequest):
        if request.pipeline_run_id not in self._prepared_runs:
            self._prepare_available_lifecycle(request.pipeline_run_id)
            self._prepared_runs.add(request.pipeline_run_id)
        return self.core.run_cycle(request)

    def release_run(self, pipeline_run_id: str) -> None:
        """Release observe-only per-run state after durable agreement capture."""
        self._release_run_total += 1
        self._prepared_runs.discard(pipeline_run_id)

        storage = getattr(self.ledger, "storage", None) or getattr(self.ledger, "_storage", None)
        discard = getattr(storage, "discard_run", None)
        if callable(discard):
            removed = int(discard(pipeline_run_id) or 0)
            self._discard_run_total += 1
            self._discarded_ledger_events_total += max(0, removed)

        paper_engine = getattr(self.core, "paper_engine", None) or getattr(self.core, "_paper_engine", None)
        orders = getattr(paper_engine, "orders", None)
        if isinstance(orders, list):
            self._paper_orders_cleared_total += len(orders)
            orders.clear()

    def owner_retention_snapshot(self) -> dict[str, int]:
        """Return bounded counters for the exact retention owners under audit."""
        storage = getattr(self.ledger, "storage", None) or getattr(self.ledger, "_storage", None)
        event_count = getattr(storage, "event_count", None)
        ledger_run_count = int(event_count()) if callable(event_count) else 0
        paper_engine = getattr(self.core, "paper_engine", None) or getattr(self.core, "_paper_engine", None)
        orders = getattr(paper_engine, "orders", None)
        return {
            "shadow_prepared_runs_count": len(self._prepared_runs),
            "shadow_paper_orders_count": len(orders) if isinstance(orders, list) else 0,
            "shadow_ledger_run_count": ledger_run_count,
            "shadow_release_run_total": self._release_run_total,
            "shadow_discard_run_total": self._discard_run_total,
            "shadow_discarded_ledger_events_total": self._discarded_ledger_events_total,
            "shadow_paper_orders_cleared_total": self._paper_orders_cleared_total,
        }

    def _prepare_available_lifecycle(self, run_id: str) -> None:
        states = (
            ScientificLifecycleState.RAW,
            ScientificLifecycleState.FEATURED,
            ScientificLifecycleState.EVIDENCE_READY,
            ScientificLifecycleState.VALIDATED,
            ScientificLifecycleState.CERTIFIED,
            ScientificLifecycleState.REGISTERED,
            ScientificLifecycleState.AVAILABLE,
        )
        for index, (before, after) in enumerate(zip(states, states[1:])):
            self.ledger.append_transition(
                pipeline_run_id=run_id,
                stage=f"gui-shadow-stage-{index}",
                state_before=before,
                state_after=after,
                succeeded=True,
                reason_codes=("GUI_SHADOW_SYNTHETIC_LIFECYCLE",),
            )


def build_gui_shadow_core_runtime() -> GuiShadowCoreRuntime:
    registry = StrategyRegistry()
    registry.register(GuiAnalysisStrategy())
    ledger = ScientificLedger(InMemoryLedgerStorage())
    paper = PaperTradingEngine(
        PaperPortfolio(starting_balance=10_000.0),
        RiskManager(
            RiskLimits(
                max_position_notional=1_000.0,
                max_total_exposure=2_000.0,
                max_leverage=1.0,
            )
        ),
    )
    core = DVSAICore(
        strategy_engine=StrategyIntelligenceEngine(registry),
        decision_bridge=StrategyDecisionBridge(
            DecisionAdapter(ledger, minimum_confidence=0.60)
        ),
        paper_engine=paper,
        event_bus=EventBus(),
        health_monitor=RuntimeHealthMonitor(),
        alerts=AlertCenter(),
    )
    return GuiShadowCoreRuntime(core=core, ledger=ledger, _prepared_runs=set())
