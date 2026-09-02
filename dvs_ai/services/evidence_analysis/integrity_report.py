from __future__ import annotations
from datetime import datetime
from math import isfinite
from .observable_models import FrozenObservableContext
from .observable_universe import ObservableUniverseEngine
from .report_models import IntegrityReport, StageState

class IntegrityReportEngine:
    """Validates only the immutable artifact. It never opens the database."""
    @staticmethod
    def build(context: FrozenObservableContext) -> IntegrityReport:
        checks=[]; reasons=[]
        verified=ObservableUniverseEngine.verify_context(context)
        checks.append(("artifact_hash", "PASS" if verified else "FAIL"))
        if not verified: reasons.append("immutable context verification failed")
        ids=list(context.observation_ids)
        expected_ids=[o.observation_id for o in context.observations]
        id_match=ids == expected_ids
        checks.append(("observation_id_linkage", "PASS" if id_match else "FAIL"))
        if not id_match: reasons.append("observation ids do not match frozen rows")
        # Duplicate (observation_id, variant) is invalid; MAIN/SHADOW may share an id.
        keys=[(o.observation_id,o.variant) for o in context.observations]
        unique=len(keys)==len(set(keys))
        checks.append(("duplicate_rows", "PASS" if unique else "FAIL"))
        if not unique: reasons.append("duplicate frozen observation rows")
        chronological=True; previous=None
        for o in context.observations:
            try: current=datetime.fromisoformat(o.created_at.replace("Z","+00:00"))
            except Exception: chronological=False; break
            if previous is not None and current < previous: chronological=False; break
            previous=current
        checks.append(("chronology", "PASS" if chronological else "FAIL"))
        if not chronological: reasons.append("chronology is invalid or out of order")
        outcomes=all(o.outcome_r is None or isfinite(float(o.outcome_r)) for o in context.observations)
        checks.append(("finite_outcomes", "PASS" if outcomes else "FAIL"))
        if not outcomes: reasons.append("non-finite outcome detected")
        filters_ok=all(
            (context.filters.regime is None or o.regime == context.filters.regime)
            and (context.filters.direction is None or o.direction == context.filters.direction)
            and (context.filters.variant is None or o.variant == context.filters.variant)
            and (context.filters.order_flow_quality is None or o.order_flow_quality == context.filters.order_flow_quality)
            for o in context.observations
        )
        checks.append(("intersection_membership", "PASS" if filters_ok else "FAIL"))
        if not filters_ok: reasons.append("row outside frozen intersection")
        state=StageState.PASS if not reasons else StageState.FAIL
        return IntegrityReport(state,tuple(checks),tuple(reasons))
