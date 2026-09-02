from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dvs_ai.services.quantum_burn_in import QuantumBurnInPolicy
from dvs_ai.services.quantum_burn_in_dashboard import BurnInDashboardService
from dvs_ai.services.quantum_burn_in_ledger import BurnInMilestoneLedger
from dvs_ai.services.quantum_burn_in_quality import BurnInQualityFilter
from dvs_ai.services.quantum_cross_pipeline_monitor import CrossPipelineMonitor
from dvs_ai.services.quantum_burn_in_snapshot_store import BurnInSnapshotStore
from dvs_ai.services.quantum_data_convergence import EpisodeOutcomeSource, PaperTradeSource, QuantumDataAdapter


@dataclass(frozen=True)
class BurnInProgramSnapshot:
    schema: str
    generated_at: str
    quality: dict[str, Any]
    burn_in: dict[str, Any]
    cross_pipeline: dict[str, Any]
    dashboard: dict[str, Any]
    milestones_appended: tuple[dict[str, Any], ...]
    authority_granted: bool
    production_or_execution_authority: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class QuantumBurnInProgram:
    """QBP-1 observe-only coordinator over converged outcome sources."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        ledger_path: str | Path | None = None,
        adapter: QuantumDataAdapter | None = None,
        history_path: str | Path | None = None,
        latest_snapshot_path: str | Path | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.adapter = adapter or QuantumDataAdapter(
            PaperTradeSource(self.db_path), EpisodeOutcomeSource(self.db_path)
        )
        self.ledger = BurnInMilestoneLedger(
            ledger_path or self.db_path.with_name("quantum_burn_in_milestones.jsonl")
        )
        self.history = BurnInSnapshotStore(
            history_path or self.db_path.with_name("quantum_burn_in_history.jsonl")
        )
        self.latest_snapshot_path = Path(
            latest_snapshot_path or self.db_path.with_name("quantum_burn_in_latest.json")
        )

    def snapshot(self, *, persist_milestones: bool = False, persist_history: bool = False) -> BurnInProgramSnapshot:
        rows = self.adapter.read_terminal()
        quality = BurnInQualityFilter().evaluate(rows)
        burn_in = QuantumBurnInPolicy.evaluate(
            quality.eligible,
            {
                "total_terminal": quality.total_terminal,
                "eligible": quality.eligible,
                "excluded": quality.excluded,
            },
        )
        cross = CrossPipelineMonitor().inspect(rows)
        dashboard = BurnInDashboardService.build(burn_in, quality, cross)
        milestones = self.ledger.record_reached(
            eligible_outcomes=quality.eligible,
            dataset_sha256=quality.dataset_sha256,
        ) if persist_milestones else []
        result = BurnInProgramSnapshot(
            schema="DVS_QBP1_REAL_BURN_IN_V1",
            generated_at=datetime.now(timezone.utc).isoformat(),
            quality=quality.to_dict(),
            burn_in=burn_in.to_dict(),
            cross_pipeline=cross.to_dict(),
            dashboard=dashboard.to_dict(),
            milestones_appended=tuple(milestones),
            authority_granted=False,
            production_or_execution_authority=False,
        )
        if persist_history:
            payload = result.to_dict()
            self.history.append(payload)
            self.history.write_latest_atomic(self.latest_snapshot_path, payload)
        return result

    def write_report(self, destination: str | Path, *, persist_milestones: bool = False, persist_history: bool = False) -> Path:
        output = Path(destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.snapshot(persist_milestones=persist_milestones, persist_history=persist_history).to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return output
