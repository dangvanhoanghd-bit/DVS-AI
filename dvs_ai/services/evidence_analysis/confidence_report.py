from __future__ import annotations
from .confidence_engine import ConfidenceEngine, ConfidenceInput
from .observable_models import FrozenObservableContext
from .report_models import ConfidenceReport, EvidenceReport, IntegrityReport

class ConfidenceReportEngine:
    """Compatibility facade over the independent ConfidenceEngine."""
    @staticmethod
    def build(context: FrozenObservableContext, integrity: IntegrityReport, evidence: EvidenceReport, *, samples: int = 2000) -> ConfidenceReport:
        return ConfidenceEngine.build(ConfidenceInput(
            protocol_version=context.protocol_version,
            context_id=context.context_id,
            context_artifact_hash=context.artifact_hash,
            observability_state=context.observability_state,
            power_state=context.power_state,
            integrity_state=integrity.state,
            evidence=evidence,
        ), samples=samples)
