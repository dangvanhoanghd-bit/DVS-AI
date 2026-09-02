from __future__ import annotations

from uuid import uuid4

from ..contracts import ScientificLifecycleState
from ..governance import DEFAULT_REASON_CODE_REGISTRY, ReasonCodeRegistry
from .models import ScientificLedgerEvent
from .storage import LedgerStorage


class ScientificLedger:
    def __init__(self, storage: LedgerStorage, *, reason_registry: ReasonCodeRegistry = DEFAULT_REASON_CODE_REGISTRY, strict_reason_codes: bool = False) -> None:
        self._storage = storage
        self._reason_registry = reason_registry
        self._strict_reason_codes = strict_reason_codes

    def append_transition(self, *, pipeline_run_id: str, stage: str,
                          state_before: ScientificLifecycleState, state_after: ScientificLifecycleState,
                          succeeded: bool, reason_codes: tuple[str, ...] = (),
                          artifact_reference: str | None = None) -> ScientificLedgerEvent:
        reason_codes = self._reason_registry.normalize(reason_codes, strict=self._strict_reason_codes)
        existing = self._storage.read_run(pipeline_run_id)
        previous_hash = existing[-1].event_hash if existing else "GENESIS"
        event = ScientificLedgerEvent.create(
            event_id=f"evt-{uuid4().hex}", pipeline_run_id=pipeline_run_id,
            sequence=len(existing), stage=stage, state_before=state_before, state_after=state_after,
            succeeded=succeeded, reason_codes=reason_codes, artifact_reference=artifact_reference,
            previous_hash=previous_hash,
        )
        self._storage.append(event)
        return event

    def read_run(self, pipeline_run_id: str) -> tuple[ScientificLedgerEvent, ...]:
        return self._storage.read_run(pipeline_run_id)

    def verify_run(self, pipeline_run_id: str) -> bool:
        events = self.read_run(pipeline_run_id)
        # Fail closed: an unknown/empty run is not a verified run.
        if not events:
            return False
        previous = "GENESIS"
        for expected_sequence, event in enumerate(events):
            if event.sequence != expected_sequence or event.previous_hash != previous or not event.verify_hash():
                return False
            previous = event.event_hash
        return True
