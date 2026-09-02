from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping

from ..contracts import ScientificLifecycleState, normalize_reason_codes


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


@dataclass(frozen=True, slots=True)
class ScientificLedgerEvent:
    event_id: str
    pipeline_run_id: str
    sequence: int
    timestamp_utc: str
    stage: str
    state_before: ScientificLifecycleState
    state_after: ScientificLifecycleState
    succeeded: bool
    reason_codes: tuple[str, ...]
    artifact_reference: str | None
    previous_hash: str
    event_hash: str

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.pipeline_run_id.strip():
            raise ValueError("event_id and pipeline_run_id are required")
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        object.__setattr__(self, "reason_codes", normalize_reason_codes(self.reason_codes))
        if not self.event_hash:
            raise ValueError("event_hash is required")

    def payload_for_hash(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "pipeline_run_id": self.pipeline_run_id,
            "sequence": self.sequence,
            "timestamp_utc": self.timestamp_utc,
            "stage": self.stage,
            "state_before": self.state_before.value,
            "state_after": self.state_after.value,
            "succeeded": self.succeeded,
            "reason_codes": list(self.reason_codes),
            "artifact_reference": self.artifact_reference,
            "previous_hash": self.previous_hash,
        }

    def verify_hash(self) -> bool:
        expected = sha256(_canonical_json(self.payload_for_hash()).encode("utf-8")).hexdigest()
        return expected == self.event_hash

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["state_before"] = self.state_before.value
        value["state_after"] = self.state_after.value
        value["reason_codes"] = list(self.reason_codes)
        return value

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        pipeline_run_id: str,
        sequence: int,
        stage: str,
        state_before: ScientificLifecycleState,
        state_after: ScientificLifecycleState,
        succeeded: bool,
        reason_codes: tuple[str, ...] = (),
        artifact_reference: str | None = None,
        previous_hash: str = "GENESIS",
        timestamp_utc: str | None = None,
    ) -> "ScientificLedgerEvent":
        timestamp = timestamp_utc or datetime.now(timezone.utc).isoformat()
        base = {
            "event_id": event_id,
            "pipeline_run_id": pipeline_run_id,
            "sequence": sequence,
            "timestamp_utc": timestamp,
            "stage": stage,
            "state_before": state_before.value,
            "state_after": state_after.value,
            "succeeded": succeeded,
            "reason_codes": list(normalize_reason_codes(reason_codes)),
            "artifact_reference": artifact_reference,
            "previous_hash": previous_hash,
        }
        digest = sha256(_canonical_json(base).encode("utf-8")).hexdigest()
        return cls(
            event_id=event_id,
            pipeline_run_id=pipeline_run_id,
            sequence=sequence,
            timestamp_utc=timestamp,
            stage=stage,
            state_before=state_before,
            state_after=state_after,
            succeeded=succeeded,
            reason_codes=tuple(base["reason_codes"]),
            artifact_reference=artifact_reference,
            previous_hash=previous_hash,
            event_hash=digest,
        )
