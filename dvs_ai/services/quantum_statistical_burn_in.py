from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from dvs_ai.services.quantum_burn_in_quality import BurnInQualityFilter, QualityReport
from dvs_ai.services.quantum_data_convergence.models import UnifiedOutcome


def _sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class QualifiedOutcome:
    identity: str
    status: str
    reasons: tuple[str, ...]
    source: str
    symbol: str
    direction: str
    regime: str
    setup_time: str
    close_time: str | None
    outcome: str
    realized_r: float | None
    record_sha256: str


@dataclass(frozen=True)
class QualificationResult:
    schema: str
    total: int
    qualified: int
    rejected: int
    pending_review: int
    dataset_sha256: str
    records: tuple[QualifiedOutcome, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OutcomeQualificationEngine:
    """QBP-2A deterministic classification above the QBP-1 quality filter.

    PENDING_REVIEW is reserved for records that are structurally sound but have
    an explicit review marker in provenance. No record is promoted to trading
    or execution authority by this engine.
    """

    REVIEW_KEYS = ("manual_review_required", "review_required", "ambiguous_linkage")

    def evaluate(self, rows: Iterable[UnifiedOutcome]) -> QualificationResult:
        materialized = list(rows)
        quality = BurnInQualityFilter().evaluate(materialized)
        decisions = {item.identity: item for item in quality.decisions}
        records: list[QualifiedOutcome] = []
        for row in materialized:
            decision = decisions[row.identity]
            review = any(bool(row.provenance.get(key)) for key in self.REVIEW_KEYS)
            if decision.eligible and review:
                status = "PENDING_REVIEW"
                reasons = ("EXPLICIT_REVIEW_MARKER",)
            elif decision.eligible:
                status = "QUALIFIED"
                reasons = ()
            else:
                status = "REJECTED"
                reasons = decision.reasons
            records.append(QualifiedOutcome(
                identity=row.identity,
                status=status,
                reasons=tuple(reasons),
                source=row.source,
                symbol=row.symbol,
                direction=row.direction,
                regime=row.regime or "UNKNOWN",
                setup_time=row.setup_time,
                close_time=row.close_time,
                outcome=row.outcome,
                realized_r=row.realized_r,
                record_sha256=decision.record_sha256,
            ))
        records.sort(key=lambda item: (item.close_time or item.setup_time, item.identity))
        qualified_rows = [
            {"identity": item.identity, "record_sha256": item.record_sha256}
            for item in records if item.status == "QUALIFIED"
        ]
        counts = Counter(item.status for item in records)
        return QualificationResult(
            schema="DVS_QBP2_OUTCOME_QUALIFICATION_V1",
            total=len(records),
            qualified=counts["QUALIFIED"],
            rejected=counts["REJECTED"],
            pending_review=counts["PENDING_REVIEW"],
            dataset_sha256=_sha256(qualified_rows),
            records=tuple(records),
        )


@dataclass(frozen=True)
class EffectiveSampleSizeResult:
    n: int
    ess: float
    lag_1_autocorrelation: float
    method: str
    state: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EffectiveSampleSizeEstimator:
    """QBP-2B conservative lag-1 ESS diagnostic for ordered realized-R data."""

    @staticmethod
    def estimate(values: Sequence[float]) -> EffectiveSampleSizeResult:
        series = [float(v) for v in values if math.isfinite(float(v))]
        n = len(series)
        if n < 2:
            return EffectiveSampleSizeResult(n, float(n), 0.0, "AR1_CONSERVATIVE_V1", "INSUFFICIENT_DATA")
        mean = sum(series) / n
        denom = sum((x - mean) ** 2 for x in series)
        if denom == 0:
            rho = 0.0
        else:
            rho = sum((series[i] - mean) * (series[i - 1] - mean) for i in range(1, n)) / denom
            rho = max(-0.99, min(0.99, rho))
        ess = n * (1.0 - rho) / (1.0 + rho)
        ess = max(1.0, min(float(n), ess))
        return EffectiveSampleSizeResult(n, round(ess, 6), round(rho, 6), "AR1_CONSERVATIVE_V1", "READY")


@dataclass(frozen=True)
class WalkForwardFold:
    index: int
    train_identities: tuple[str, ...]
    test_identities: tuple[str, ...]
    purged_identities: tuple[str, ...]
    embargoed_identities: tuple[str, ...]


@dataclass(frozen=True)
class WalkForwardPlan:
    state: str
    folds: tuple[WalkForwardFold, ...]
    purge: int
    embargo: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WalkForwardDatasetBuilder:
    """QBP-2C deterministic chronological folds with purge and embargo gaps."""

    def build(self, rows: Sequence[QualifiedOutcome], *, folds: int = 5, purge: int = 1, embargo: int = 1) -> WalkForwardPlan:
        qualified = [row for row in rows if row.status == "QUALIFIED"]
        qualified.sort(key=lambda row: (row.close_time or row.setup_time, row.identity))
        n = len(qualified)
        if folds < 1 or purge < 0 or embargo < 0:
            raise ValueError("invalid walk-forward parameters")
        if n < max(2, folds):
            return WalkForwardPlan("INSUFFICIENT_DATA", (), purge, embargo)
        test_size = max(1, n // (folds + 1))
        built: list[WalkForwardFold] = []
        for index in range(folds):
            test_start = n - (folds - index) * test_size
            test_end = min(n, test_start + test_size)
            if test_start <= 0:
                continue
            train_end = max(0, test_start - purge)
            embargo_end = min(n, test_end + embargo)
            built.append(WalkForwardFold(
                index=len(built),
                train_identities=tuple(row.identity for row in qualified[:train_end]),
                test_identities=tuple(row.identity for row in qualified[test_start:test_end]),
                purged_identities=tuple(row.identity for row in qualified[train_end:test_start]),
                embargoed_identities=tuple(row.identity for row in qualified[test_end:embargo_end]),
            ))
        return WalkForwardPlan("READY" if built else "INSUFFICIENT_DATA", tuple(built), purge, embargo)


@dataclass(frozen=True)
class DatasetIntegrityReport:
    qualified: int
    by_source: dict[str, int]
    by_symbol: dict[str, int]
    by_direction: dict[str, int]
    by_regime: dict[str, int]
    by_outcome: dict[str, int]
    warnings: tuple[str, ...]
    dataset_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DatasetIntegrityAuditor:
    """QBP-2D descriptive integrity checks; warnings never unlock authority."""

    def inspect(self, result: QualificationResult) -> DatasetIntegrityReport:
        rows = [item for item in result.records if item.status == "QUALIFIED"]
        warnings: list[str] = []
        if not rows:
            warnings.append("NO_QUALIFIED_OUTCOMES")
        directions = Counter(item.direction.upper() for item in rows)
        if rows and len(directions) < 2:
            warnings.append("DIRECTION_COVERAGE_SINGLE_SIDED")
        outcomes = Counter(item.outcome for item in rows)
        if rows and len(outcomes) < 2:
            warnings.append("OUTCOME_COVERAGE_SINGLE_CLASS")
        regimes = Counter(item.regime for item in rows)
        if rows and set(regimes) == {"UNKNOWN"}:
            warnings.append("REGIME_COVERAGE_UNKNOWN")
        symbols = Counter(item.symbol for item in rows)
        if rows and max(symbols.values()) / len(rows) > 0.8:
            warnings.append("SYMBOL_CONCENTRATION_ABOVE_80_PERCENT")
        return DatasetIntegrityReport(
            qualified=len(rows),
            by_source=dict(sorted(Counter(item.source for item in rows).items())),
            by_symbol=dict(sorted(symbols.items())),
            by_direction=dict(sorted(directions.items())),
            by_regime=dict(sorted(regimes.items())),
            by_outcome=dict(sorted(outcomes.items())),
            warnings=tuple(sorted(warnings)),
            dataset_sha256=result.dataset_sha256,
        )


@dataclass(frozen=True)
class StatisticalReadinessReport:
    schema: str
    generated_at: str
    state: str
    qualified_outcomes: int
    ess: dict[str, Any]
    walk_forward: dict[str, Any]
    integrity: dict[str, Any]
    capabilities: dict[str, bool]
    blockers: tuple[str, ...]
    authority_granted: bool
    production_or_execution_authority: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StatisticalBurnInService:
    """QBP-2E observe-only statistical readiness coordinator."""

    def evaluate(self, rows: Iterable[UnifiedOutcome]) -> StatisticalReadinessReport:
        qualification = OutcomeQualificationEngine().evaluate(rows)
        qualified = [item for item in qualification.records if item.status == "QUALIFIED"]
        ess = EffectiveSampleSizeEstimator.estimate([float(item.realized_r) for item in qualified if item.realized_r is not None])
        walk_forward = WalkForwardDatasetBuilder().build(qualification.records)
        integrity = DatasetIntegrityAuditor().inspect(qualification)
        count = qualification.qualified
        capabilities = {
            "outcome_qualification": True,
            "effective_sample_size": count >= 100,
            "walk_forward": count >= 100,
            "purge_embargo": count >= 100,
        }
        blockers: list[str] = []
        if count < 100:
            blockers.append(f"QUALIFIED_OUTCOMES_BELOW_100:{count}")
        if qualification.pending_review:
            blockers.append(f"PENDING_REVIEW_OUTCOMES:{qualification.pending_review}")
        blockers.extend(f"INTEGRITY_WARNING:{item}" for item in integrity.warnings)
        state = "QBP2_STATISTICAL_READY" if all(capabilities.values()) and not blockers else "QBP2_COLLECTION_OR_REVIEW_REQUIRED"
        return StatisticalReadinessReport(
            schema="DVS_QBP2_STATISTICAL_BURN_IN_V1",
            generated_at=datetime.now(timezone.utc).isoformat(),
            state=state,
            qualified_outcomes=count,
            ess=ess.to_dict(),
            walk_forward=walk_forward.to_dict(),
            integrity=integrity.to_dict(),
            capabilities=capabilities,
            blockers=tuple(blockers),
            authority_granted=False,
            production_or_execution_authority=False,
        )
