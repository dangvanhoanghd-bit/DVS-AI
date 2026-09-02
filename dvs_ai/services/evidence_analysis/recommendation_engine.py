from __future__ import annotations
from dataclasses import dataclass
from .observable_models import FrozenObservableContext
from .report_models import ActionableGapReport, ConfidenceReport, EvidenceReport, IntegrityReport, RecommendationResult
from .recommendation_mapper import RecommendationMapper, RecommendationStateInput

@dataclass(frozen=True)
class RecommendationInput:
    context: FrozenObservableContext
    integrity: IntegrityReport
    evidence: EvidenceReport
    confidence: ConfidenceReport
    gap: ActionableGapReport

class RecommendationEngine:
    """Compatibility facade. The mapper receives normalized states only."""
    @staticmethod
    def build(payload: RecommendationInput) -> RecommendationResult:
        return RecommendationMapper.build(RecommendationStateInput(
            integrity_state=payload.integrity.state,
            observability_state=payload.context.observability_state.value,
            power_state=payload.context.power_state.value,
            confidence_stage=payload.confidence.state,
            conclusion_state=payload.confidence.conclusion_state,
        ))
