from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from dvs_ai.services.quantum_data_convergence.models import UnifiedOutcome
from dvs_ai.services.quantum_readiness_service import QuantumReadinessService


def _sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class QualityDecision:
    identity: str
    eligible: bool
    reasons: tuple[str, ...]
    source: str
    outcome: str
    record_sha256: str


@dataclass(frozen=True)
class QualityReport:
    total_terminal: int
    eligible: int
    excluded: int
    by_source: dict[str, int]
    by_outcome: dict[str, int]
    exclusion_reasons: dict[str, int]
    eligible_identities: tuple[str, ...]
    dataset_sha256: str
    decisions: tuple[QualityDecision, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BurnInQualityFilter:
    """Deterministic, read-only eligibility filter for real burn-in outcomes.

    Only determinate WIN/LOSS records with valid DVS_QUANTUM_TRAINING_V1
    evidence and validated/stable/full truth states are counted. The filter
    never mutates storage and never grants runtime or trading authority.
    """

    @staticmethod
    def _canonical_record(row: UnifiedOutcome) -> dict[str, Any]:
        return {
            "identity": row.identity,
            "source": row.source,
            "source_id": row.source_id,
            "symbol": row.symbol,
            "direction": row.direction,
            "setup_time": row.setup_time,
            "close_time": row.close_time,
            "outcome": row.outcome,
            "realized_r": row.realized_r,
            "confidence": row.confidence,
            "entry_score": row.entry_score,
            "risk_score": row.risk_score,
            "rr_planned": row.rr_planned,
            "cohort": row.cohort,
            "regime": row.regime,
            "evidence_snapshot": row.evidence_snapshot,
            "original_status": row.original_status,
            "original_result": row.original_result,
            "provenance": row.provenance,
        }

    def evaluate(self, rows: Iterable[UnifiedOutcome]) -> QualityReport:
        materialized = list(rows)
        identities = [row.identity for row in materialized]
        duplicate_ids = {key for key, count in Counter(identities).items() if count > 1}
        decisions: list[QualityDecision] = []

        for row in materialized:
            reasons: list[str] = []
            if row.identity in duplicate_ids:
                reasons.append("DUPLICATE_IDENTITY")
            if row.outcome not in {"WIN", "LOSS"}:
                reasons.append("NON_DETERMINATE_OUTCOME")
            if row.close_time is None or not str(row.close_time).strip():
                reasons.append("MISSING_CLOSE_TIME")
            if row.realized_r is None:
                reasons.append("MISSING_REALIZED_R")
            else:
                try:
                    value = float(row.realized_r)
                    if not math.isfinite(value):
                        reasons.append("NON_FINITE_REALIZED_R")
                except (TypeError, ValueError):
                    reasons.append("NON_FINITE_REALIZED_R")
            snapshot = row.evidence_snapshot
            if snapshot is None:
                reasons.append("MISSING_EVIDENCE_SNAPSHOT")
            elif not QuantumReadinessService._valid_snapshot(snapshot):
                reasons.append("INVALID_EVIDENCE_SNAPSHOT")
            else:
                truth = snapshot["_TRUTH"]
                if str(truth.get("calibration_state", "")).upper() != "VALIDATED":
                    reasons.append("CALIBRATION_NOT_VALIDATED")
                if str(truth.get("drift_state", "")).upper() != "STABLE":
                    reasons.append("DRIFT_NOT_STABLE")
                if str(truth.get("order_flow_quality", "")).upper() != "FULL":
                    reasons.append("ORDER_FLOW_NOT_FULL")

            canonical = self._canonical_record(row)
            decisions.append(QualityDecision(
                identity=row.identity,
                eligible=not reasons,
                reasons=tuple(sorted(set(reasons))),
                source=row.source,
                outcome=row.outcome,
                record_sha256=_sha256(canonical),
            ))

        eligible_ids = tuple(sorted(item.identity for item in decisions if item.eligible))
        digest_rows = [
            {"identity": item.identity, "record_sha256": item.record_sha256}
            for item in sorted(decisions, key=lambda item: item.identity)
            if item.eligible
        ]
        reason_counts = Counter(reason for item in decisions for reason in item.reasons)
        return QualityReport(
            total_terminal=len(materialized),
            eligible=len(eligible_ids),
            excluded=len(materialized) - len(eligible_ids),
            by_source=dict(sorted(Counter(row.source for row in materialized).items())),
            by_outcome=dict(sorted(Counter(row.outcome for row in materialized).items())),
            exclusion_reasons=dict(sorted(reason_counts.items())),
            eligible_identities=eligible_ids,
            dataset_sha256=_sha256(digest_rows),
            decisions=tuple(decisions),
        )
