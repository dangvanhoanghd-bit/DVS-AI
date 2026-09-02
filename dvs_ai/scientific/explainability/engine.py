from __future__ import annotations

from ..contracts import ScientificLifecycleState
from ..governance import DEFAULT_REASON_CODE_REGISTRY, ReasonCodeRegistry
from ..ledger import ScientificLedger
from .models import ExplanationStep, ScientificExplanation


class ScientificExplainabilityEngine:
    def __init__(self, ledger: ScientificLedger, *, registry: ReasonCodeRegistry = DEFAULT_REASON_CODE_REGISTRY) -> None:
        self._ledger = ledger
        self._registry = registry

    def explain_run(self, run_id: str) -> ScientificExplanation:
        events = self._ledger.read_run(run_id)
        integrity = self._ledger.verify_run(run_id)
        if not events:
            raise ValueError(f"scientific run not found: {run_id}")
        steps = []
        reasons: list[str] = []
        for event in events:
            for code in event.reason_codes:
                definition = self._registry.require(code)
                if code not in reasons:
                    reasons.append(code)
            if event.succeeded:
                narrative = f"{event.stage} advanced {event.state_before.value} to {event.state_after.value}."
            else:
                detail = "; ".join(self._registry.require(c).description for c in event.reason_codes) or "Unspecified failure"
                narrative = f"{event.stage} stopped the lifecycle: {detail}."
            steps.append(ExplanationStep(
                sequence=event.sequence, stage=event.stage,
                state_before=event.state_before, state_after=event.state_after,
                succeeded=event.succeeded, reason_codes=event.reason_codes,
                narrative=narrative,
            ))
        final_state = events[-1].state_after
        succeeded = final_state is ScientificLifecycleState.AVAILABLE and integrity
        summary = (
            f"Run {run_id} is AVAILABLE with a verified ledger."
            if succeeded else
            f"Run {run_id} ended in {final_state.value}; ledger integrity is {'verified' if integrity else 'invalid'}."
        )
        return ScientificExplanation(
            run_id=run_id, final_state=final_state, succeeded=succeeded,
            integrity_verified=integrity, steps=tuple(steps),
            primary_reason_codes=tuple(reasons), summary=summary,
        )
