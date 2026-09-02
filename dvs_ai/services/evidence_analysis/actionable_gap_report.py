from __future__ import annotations
from .gap_planner import GapPlanner, GapPlanningInput
from .observable_models import FrozenObservableContext
from .observable_thresholds import ObservableThresholdProfile
from .report_models import ActionableGapReport

class ActionableGapReportEngine:
    """Compatibility facade over the storage-independent GapPlanner."""
    @staticmethod
    def build(context: FrozenObservableContext, profile: ObservableThresholdProfile, *, paired: bool = False) -> ActionableGapReport:
        return GapPlanner.build(GapPlanningInput(
            context_id=context.context_id,
            sample_count=context.sample_count,
            paired_sample_count=context.paired_sample_count,
            observability_state=context.observability_state,
            power_state=context.power_state,
            created_at_values=tuple(o.created_at for o in context.observations),
            paired=paired,
        ), profile)
