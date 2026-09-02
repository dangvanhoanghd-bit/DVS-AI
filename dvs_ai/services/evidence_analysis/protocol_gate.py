from __future__ import annotations
from .observable_models import FrozenObservableContext, ObservableState, PowerState, RecommendationGateResult
from .observable_universe import ObservableUniverseEngine

def recommendation_gate(context: FrozenObservableContext)->RecommendationGateResult:
    if not ObservableUniverseEngine.verify_context(context): return RecommendationGateResult("ANALYSIS_ABORTED","immutable context verification failed",False)
    if context.observability_state is not ObservableState.OBSERVABLE: return RecommendationGateResult("SKIPPED",f"context state {context.observability_state.value}",False)
    if context.power_state is not PowerState.POWERED: return RecommendationGateResult("SKIPPED","context is not statistically powered",False)
    return RecommendationGateResult("ALLOWED","observable and powered immutable context",True)
