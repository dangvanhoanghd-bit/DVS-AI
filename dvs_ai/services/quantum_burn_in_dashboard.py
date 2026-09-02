from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from dvs_ai.services.quantum_burn_in import BurnInSnapshot
from dvs_ai.services.quantum_burn_in_quality import QualityReport
from dvs_ai.services.quantum_cross_pipeline_monitor import CrossPipelineReport


@dataclass(frozen=True)
class BurnInDashboardSnapshot:
    stage: str
    state: str
    eligible: int
    next_threshold: int | None
    missing_to_next: int
    progress_percent: int
    capabilities: dict[str, bool]
    quality_exclusions: dict[str, int]
    source_counts: dict[str, int]
    cross_pipeline_action: str
    exact_overlap_count: int
    potential_overlap_count: int
    authority_granted: bool
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BurnInDashboardService:
    @staticmethod
    def build(
        burn_in: BurnInSnapshot,
        quality: QualityReport,
        cross_pipeline: CrossPipelineReport,
    ) -> BurnInDashboardSnapshot:
        target = burn_in.next_threshold or max(500, burn_in.eligible_outcomes)
        previous = 0
        for threshold in (30, 100, 300, 500):
            if burn_in.eligible_outcomes >= threshold:
                previous = threshold
        span = max(1, target - previous)
        percent = max(0, min(100, round(100 * (burn_in.eligible_outcomes - previous) / span)))
        return BurnInDashboardSnapshot(
            stage=burn_in.stage,
            state=burn_in.state,
            eligible=burn_in.eligible_outcomes,
            next_threshold=burn_in.next_threshold,
            missing_to_next=burn_in.missing_to_next,
            progress_percent=percent,
            capabilities={item.name: item.enabled for item in burn_in.capabilities},
            quality_exclusions=dict(quality.exclusion_reasons),
            source_counts=dict(quality.by_source),
            cross_pipeline_action=cross_pipeline.action,
            exact_overlap_count=len(cross_pipeline.exact_link_overlaps),
            potential_overlap_count=len(cross_pipeline.potential_overlaps),
            authority_granted=False,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
