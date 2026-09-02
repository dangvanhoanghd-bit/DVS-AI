from __future__ import annotations

from ..contracts import ScientificLifecycleState, ScientificReasonCode, can_transition
from ..governance import DEFAULT_REASON_CODE_REGISTRY, ReasonCodeRegistry
from ..ledger import ScientificLedger
from .models import ReplayResult


class ScientificReplayEngine:
    """Deterministically verifies and replays a persisted scientific lifecycle."""

    def __init__(self, ledger: ScientificLedger, *, registry: ReasonCodeRegistry = DEFAULT_REASON_CODE_REGISTRY) -> None:
        self._ledger = ledger
        self._registry = registry

    def replay(self, run_id: str) -> ReplayResult:
        events = self._ledger.read_run(run_id)
        if not events:
            return ReplayResult(run_id, False, None, 0, (ScientificReasonCode.LEDGER_INTEGRITY_FAILED.value,))
        if not self._ledger.verify_run(run_id):
            return ReplayResult(run_id, False, None, 0, (ScientificReasonCode.LEDGER_INTEGRITY_FAILED.value,))
        current = events[0].state_before
        count = 0
        for event in events:
            for code in event.reason_codes:
                self._registry.require(code)
            if event.state_before is not current or not can_transition(current, event.state_after):
                return ReplayResult(run_id, False, current, count, (ScientificReasonCode.REPLAY_TRANSITION_INVALID.value,))
            current = event.state_after
            count += 1
        return ReplayResult(run_id, True, current, count)
