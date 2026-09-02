from __future__ import annotations
from .actionable_gap_report import ActionableGapReportEngine
from .confidence_report import ConfidenceReportEngine
from .evidence_report import EvidenceReportEngine
from .integrity_report import IntegrityReportEngine
from .recommendation_engine import RecommendationEngine, RecommendationInput
from .report_models import EvidenceAnalysisResult

class EvidenceAnalysisPipeline:
    def __init__(self, profile): self.profile=profile
    def run(self, context, *, paired:bool=False)->EvidenceAnalysisResult:
        integrity=IntegrityReportEngine.build(context)
        evidence=EvidenceReportEngine.build(context,integrity)
        confidence=ConfidenceReportEngine.build(context,integrity,evidence)
        gap=ActionableGapReportEngine.build(context,self.profile,paired=paired)
        recommendation=RecommendationEngine.build(RecommendationInput(context,integrity,evidence,confidence,gap))
        return EvidenceAnalysisResult(context.protocol_version,context.context_id,integrity,evidence,confidence,gap,recommendation)
