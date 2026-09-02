from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from .observable_models import ObservableState, PowerState
from .observable_thresholds import ObservableThresholdProfile
from .report_models import ActionableGapReport, GapItem, StageState

@dataclass(frozen=True)
class GapPlanningInput:
    context_id: str
    sample_count: int
    paired_sample_count: int
    observability_state: ObservableState
    power_state: PowerState
    created_at_values: tuple[str, ...]
    paired: bool = False

class GapPlanner:
    """Pure planner. It receives frozen counts/timestamps and never opens storage."""
    @staticmethod
    def _velocity(values: tuple[str, ...], count: int) -> tuple[float | None, bool]:
        dates = []
        for raw in values:
            try:
                dates.append(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
            except Exception:
                continue
        if len(dates) < 3 or count < 3:
            return None, False
        span_days = (max(dates) - min(dates)).total_seconds() / 86400.0
        if span_days < 1.0:
            return None, False
        velocity = count / span_days
        # ETA is marked reliable only when history spans at least 3 days.
        return velocity, span_days >= 1.0

    @classmethod
    def build(cls, payload: GapPlanningInput, profile: ObservableThresholdProfile) -> ActionableGapReport:
        current = payload.paired_sample_count if payload.paired else payload.sample_count
        observable_key = "paired_observable" if payload.paired else "regime_observable"
        powered_key = "paired_powered" if payload.paired else "powered_samples"
        observable = profile.get(observable_key)
        powered = profile.get(powered_key)
        target = observable if current < observable else powered
        missing = max(0, target - current)
        velocity, reliable = cls._velocity(payload.created_at_values, current)
        eta = missing / velocity if missing and reliable and velocity and velocity > 0 else None
        if missing:
            dimension = "paired intersection" if payload.paired else "intersection"
            reason = f"need {missing} additional qualified observations to reach {'observable' if target == observable else 'powered'} threshold"
            return ActionableGapReport(StageState.PASS, (GapItem(dimension, current, target, missing, eta),), reason, velocity, reliable)
        return ActionableGapReport(StageState.PASS, (), "no observable/power gap", velocity, reliable)
