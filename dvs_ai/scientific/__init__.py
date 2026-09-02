"""Scientific contracts and fail-closed lifecycle orchestration for DVS AI Alpha."""

from . import contracts
from .pipeline import PipelineEvent, ScientificLifecyclePipeline, ScientificPipelineResult

__all__ = ["contracts", "PipelineEvent", "ScientificLifecyclePipeline", "ScientificPipelineResult"]

# M6 public API
from .decision import DecisionAction, DecisionAdapter, DecisionRequest, ScientificDecision
from .shadow import ShadowHorizon, ShadowMetrics, ShadowObservation, ShadowValidator, InMemoryShadowStorage
from .reporting import ScientificDecisionReport, ScientificDecisionReportBuilder
