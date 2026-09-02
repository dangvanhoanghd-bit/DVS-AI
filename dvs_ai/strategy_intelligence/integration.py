from __future__ import annotations

from dataclasses import dataclass

from dvs_ai.scientific.decision import (
    DecisionAction,
    DecisionAdapter,
    DecisionRequest,
    ScientificDecision,
)

from .models import FusedSignal, MarketSnapshot, SignalDirection


@dataclass(frozen=True, slots=True)
class StrategyDecisionBridge:
    """Fail-closed bridge from M9 fused intelligence into the scientific decision gate."""

    adapter: DecisionAdapter
    model_id: str = "strategy-intelligence-m9"

    def authorize(
        self,
        *,
        pipeline_run_id: str,
        snapshot: MarketSnapshot,
        fused_signal: FusedSignal,
    ) -> ScientificDecision:
        action = {
            SignalDirection.LONG: DecisionAction.BUY,
            SignalDirection.SHORT: DecisionAction.SELL,
            SignalDirection.NEUTRAL: DecisionAction.HOLD,
        }[fused_signal.direction]
        features = {
            "m9_long_score": fused_signal.long_score,
            "m9_short_score": fused_signal.short_score,
            "m9_regime": fused_signal.regime.value,
            "m9_contributor_count": float(len(fused_signal.contributors)),
        }
        request = DecisionRequest(
            pipeline_run_id=pipeline_run_id,
            symbol=snapshot.symbol,
            proposed_action=action,
            confidence=fused_signal.confidence,
            model_id=self.model_id,
            features=features,
            created_at=snapshot.observed_at,
        )
        decision = self.adapter.authorize(request)
        # A neutral fused signal must never become an executable authorization.
        if fused_signal.direction is SignalDirection.NEUTRAL and decision.authorized:
            return ScientificDecision(
                decision_id=decision.decision_id,
                pipeline_run_id=decision.pipeline_run_id,
                symbol=decision.symbol,
                proposed_action=decision.proposed_action,
                final_action=DecisionAction.NO_ACTION,
                confidence=decision.confidence,
                authorized=False,
                reason_codes=tuple(dict.fromkeys(decision.reason_codes + ("M9_NEUTRAL_SIGNAL",))),
                model_id=decision.model_id,
                created_at=decision.created_at,
            )
        return decision
