from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from dvs_ai.services.quantum_readiness_service import QuantumReadinessService


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BurnInCapability:
    name: str
    minimum_outcomes: int
    enabled: bool


@dataclass(frozen=True)
class BurnInSnapshot:
    state: str
    stage: str
    eligible_outcomes: int
    next_threshold: int | None
    missing_to_next: int
    capabilities: tuple[BurnInCapability, ...]
    paper_authority_handover_eligible: bool
    authority_granted: bool
    generated_at: str
    readiness_audit: dict[str, int]
    self_sha256: str | None = None

    def capability_enabled(self, name: str) -> bool:
        return any(item.name == name and item.enabled for item in self.capabilities)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("self_sha256", None)
        payload["self_sha256"] = _canonical_sha256(payload)
        return payload


class QuantumBurnInPolicy:
    """Outcome-count policy for QBP-0E.

    This policy unlocks research diagnostics only.  It never grants optimizer,
    SHADOW, MAIN, recommendation, or trade-execution authority.
    """

    THRESHOLDS = (30, 100, 300, 500)
    CAPABILITY_MINIMUMS = {
        "descriptive_monitoring": 0,
        "resolved_outcome_review": 30,
        "effective_sample_size": 100,
        "walk_forward": 100,
        "purge_embargo": 100,
        "bootstrap": 300,
        "stability": 300,
        "multiple_comparison": 300,
        "paper_authority_handover_review": 500,
    }

    @classmethod
    def evaluate(cls, eligible_outcomes: int, readiness_audit: dict[str, int] | None = None) -> BurnInSnapshot:
        count = max(0, int(eligible_outcomes))
        if count < 30:
            stage, state = "QBP-0E_COLLECTING", "INSUFFICIENT_BURN_IN"
        elif count < 100:
            stage, state = "QBP-1_30_OUTCOMES", "EARLY_BURN_IN"
        elif count < 300:
            stage, state = "QBP-2_100_OUTCOMES", "VALIDATION_BURN_IN"
        elif count < 500:
            stage, state = "QBP-3_300_OUTCOMES", "STATISTICAL_BURN_IN"
        else:
            stage, state = "QBP-4_500_PLUS", "HANDOVER_REVIEW_ELIGIBLE"
        next_threshold = next((x for x in cls.THRESHOLDS if count < x), None)
        capabilities = tuple(
            BurnInCapability(name, minimum, count >= minimum)
            for name, minimum in cls.CAPABILITY_MINIMUMS.items()
        )
        snapshot = BurnInSnapshot(
            state=state,
            stage=stage,
            eligible_outcomes=count,
            next_threshold=next_threshold,
            missing_to_next=max(0, (next_threshold or count) - count),
            capabilities=capabilities,
            paper_authority_handover_eligible=count >= 500,
            authority_granted=False,
            generated_at=datetime.now(timezone.utc).isoformat(),
            readiness_audit=dict(readiness_audit or {}),
        )
        return snapshot

    @classmethod
    def missing_capabilities(cls, eligible_outcomes: int, required: Iterable[str]) -> tuple[str, ...]:
        snapshot = cls.evaluate(eligible_outcomes)
        known = {item.name: item.enabled for item in snapshot.capabilities}
        return tuple(sorted(name for name in required if not known.get(name, False)))


class QuantumBurnInService:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def snapshot(self) -> BurnInSnapshot:
        readiness = QuantumReadinessService(self.db_path, required=500).snapshot()
        return QuantumBurnInPolicy.evaluate(readiness.eligible, readiness.audit)

    def write_report(self, destination: str | Path) -> Path:
        output = Path(destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.snapshot().to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return output
