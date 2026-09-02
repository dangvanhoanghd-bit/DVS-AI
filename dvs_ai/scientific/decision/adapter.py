from __future__ import annotations
from uuid import uuid4
from ..contracts import ScientificLifecycleState
from ..ledger import ScientificLedger
from .models import DecisionAction, DecisionRequest, ScientificDecision

class DecisionAdapter:
    """Read-only bridge from a verified Scientific Core run to a decision."""
    def __init__(self, ledger: ScientificLedger, *, minimum_confidence: float = 0.60) -> None:
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be between 0 and 1")
        self._ledger = ledger
        self._minimum_confidence = minimum_confidence

    def authorize(self, request: DecisionRequest) -> ScientificDecision:
        codes: list[str] = []
        authorized = True
        if not self._ledger.verify_run(request.pipeline_run_id):
            codes.append("LEDGER_INTEGRITY_FAILED")
            authorized = False
        events = self._ledger.read_run(request.pipeline_run_id)
        if not events or events[-1].state_after is not ScientificLifecycleState.AVAILABLE or not events[-1].succeeded:
            codes.append("DECISION_SCIENTIFIC_RUN_NOT_AVAILABLE")
            authorized = False
        if request.confidence < self._minimum_confidence:
            codes.append("DECISION_CONFIDENCE_TOO_LOW")
            authorized = False
        final_action = request.proposed_action if authorized else DecisionAction.NO_ACTION
        return ScientificDecision(
            decision_id=f"dec-{uuid4().hex}", pipeline_run_id=request.pipeline_run_id,
            symbol=request.symbol, proposed_action=request.proposed_action,
            final_action=final_action, confidence=request.confidence,
            authorized=authorized, reason_codes=tuple(codes), model_id=request.model_id,
            created_at=request.created_at,
        )
