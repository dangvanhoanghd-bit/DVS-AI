from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dvs_ai.services.quantum_burn_in_ledger import BurnInMilestoneLedger
from dvs_ai.services.quantum_burn_in_program import QuantumBurnInProgram
from dvs_ai.services.quantum_burn_in_snapshot_store import BurnInSnapshotStore


@dataclass(frozen=True)
class QBP1Qualification:
    status: str
    checks: dict[str, bool]
    eligible_outcomes: int
    stage: str
    cross_pipeline_action: str
    authority_granted: bool
    production_or_execution_authority: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class QBP1ReleaseQualifier:
    """Qualifies QBP-1 infrastructure for observe-only real-data collection."""

    def __init__(self, db_path: str | Path, *, ledger_path: str | Path, history_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.ledger = BurnInMilestoneLedger(ledger_path)
        self.history = BurnInSnapshotStore(history_path)

    def evaluate(self) -> QBP1Qualification:
        snapshot = QuantumBurnInProgram(self.db_path, ledger_path=self.ledger.path).snapshot(persist_milestones=False).to_dict()
        checks = {
            "database_exists": self.db_path.exists(),
            "milestone_ledger_valid": self.ledger.verify(),
            "snapshot_history_valid": self.history.verify(),
            "authority_locked": snapshot.get("authority_granted") is False,
            "execution_authority_locked": snapshot.get("production_or_execution_authority") is False,
            "quality_digest_present": bool(snapshot.get("quality", {}).get("dataset_sha256")),
            "dashboard_consistent": snapshot.get("dashboard", {}).get("eligible") == snapshot.get("quality", {}).get("eligible"),
        }
        if not all(checks.values()):
            status = "BLOCKED_NOT_QUALIFIED"
        elif snapshot.get("cross_pipeline", {}).get("action") == "REVIEW_REQUIRED":
            status = "QUALIFIED_OBSERVE_ONLY_REVIEW_REQUIRED"
        else:
            status = "QUALIFIED_OBSERVE_ONLY_COLLECTION"
        return QBP1Qualification(
            status=status,
            checks=checks,
            eligible_outcomes=int(snapshot["quality"]["eligible"]),
            stage=str(snapshot["burn_in"]["stage"]),
            cross_pipeline_action=str(snapshot["cross_pipeline"]["action"]),
            authority_granted=False,
            production_or_execution_authority=False,
        )
