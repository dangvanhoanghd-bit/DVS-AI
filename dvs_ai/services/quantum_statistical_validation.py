from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from dvs_ai.services.quantum_data_convergence.models import UnifiedOutcome
from dvs_ai.services.quantum_statistical_burn_in import OutcomeQualificationEngine, QualifiedOutcome


def _sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        raise ValueError("quantile requires non-empty values")
    ordered = sorted(float(v) for v in values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


@dataclass(frozen=True)
class BootstrapReport:
    state: str
    n: int
    iterations: int
    seed_sha256: str
    mean_realized_r: float | None
    confidence_level: float
    ci_low: float | None
    ci_high: float | None
    probability_mean_positive: float | None
    method: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DeterministicBootstrapValidator:
    """QBP-3 deterministic non-parametric bootstrap for mean realized-R.

    It is a research diagnostic only.  The seed derives from the qualified
    dataset digest, making repeated audits reproducible without global RNG use.
    """

    def evaluate(
        self,
        values: Sequence[float],
        *,
        dataset_sha256: str,
        iterations: int = 2000,
        confidence_level: float = 0.95,
        minimum_n: int = 300,
    ) -> BootstrapReport:
        series = [float(v) for v in values if math.isfinite(float(v))]
        n = len(series)
        if iterations < 100:
            raise ValueError("bootstrap iterations must be >= 100")
        if not 0.5 < confidence_level < 1.0:
            raise ValueError("confidence_level must be between 0.5 and 1.0")
        seed_material = f"DVS_QBP3_BOOTSTRAP_V1:{dataset_sha256}:{iterations}:{confidence_level}"
        seed_digest = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
        if n < minimum_n:
            return BootstrapReport(
                "LOCKED_INSUFFICIENT_DATA", n, iterations, seed_digest, None,
                confidence_level, None, None, None, "PERCENTILE_BOOTSTRAP_MEAN_R_V1",
            )
        rng = random.Random(int(seed_digest[:16], 16))
        means: list[float] = []
        for _ in range(iterations):
            means.append(sum(series[rng.randrange(n)] for _ in range(n)) / n)
        alpha = (1.0 - confidence_level) / 2.0
        observed = sum(series) / n
        return BootstrapReport(
            state="READY",
            n=n,
            iterations=iterations,
            seed_sha256=seed_digest,
            mean_realized_r=round(observed, 8),
            confidence_level=confidence_level,
            ci_low=round(_quantile(means, alpha), 8),
            ci_high=round(_quantile(means, 1.0 - alpha), 8),
            probability_mean_positive=round(sum(1 for value in means if value > 0.0) / iterations, 8),
            method="PERCENTILE_BOOTSTRAP_MEAN_R_V1",
        )


@dataclass(frozen=True)
class StabilityWindow:
    index: int
    identities: tuple[str, ...]
    n: int
    mean_realized_r: float
    win_rate: float


@dataclass(frozen=True)
class StabilityReport:
    state: str
    n: int
    windows: tuple[StabilityWindow, ...]
    mean_dispersion: float | None
    positive_window_fraction: float | None
    direction_coverage: dict[str, int]
    regime_coverage: dict[str, int]
    warnings: tuple[str, ...]
    method: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChronologicalStabilityValidator:
    """QBP-3 stability diagnostics across deterministic chronological windows."""

    def evaluate(
        self,
        rows: Sequence[QualifiedOutcome],
        *,
        windows: int = 6,
        minimum_n: int = 300,
    ) -> StabilityReport:
        qualified = [row for row in rows if row.status == "QUALIFIED" and row.realized_r is not None]
        qualified.sort(key=lambda row: (row.close_time or row.setup_time, row.identity))
        n = len(qualified)
        if windows < 2:
            raise ValueError("windows must be >= 2")
        if n < minimum_n:
            return StabilityReport(
                "LOCKED_INSUFFICIENT_DATA", n, (), None, None, {}, {},
                (f"QUALIFIED_OUTCOMES_BELOW_{minimum_n}:{n}",), "CHRONOLOGICAL_WINDOWS_V1",
            )
        size = n // windows
        built: list[StabilityWindow] = []
        for idx in range(windows):
            start = idx * size
            end = n if idx == windows - 1 else (idx + 1) * size
            chunk = qualified[start:end]
            values = [float(row.realized_r) for row in chunk]
            built.append(StabilityWindow(
                index=idx,
                identities=tuple(row.identity for row in chunk),
                n=len(chunk),
                mean_realized_r=round(sum(values) / len(values), 8),
                win_rate=round(sum(1 for row in chunk if row.outcome == "WIN") / len(chunk), 8),
            ))
        means = [window.mean_realized_r for window in built]
        overall = sum(means) / len(means)
        dispersion = math.sqrt(sum((value - overall) ** 2 for value in means) / len(means))
        positive_fraction = sum(1 for value in means if value > 0.0) / len(means)
        warnings: list[str] = []
        if positive_fraction < 0.5:
            warnings.append("POSITIVE_WINDOWS_BELOW_50_PERCENT")
        if dispersion > max(0.5, abs(overall) * 2.0):
            warnings.append("WINDOW_MEAN_DISPERSION_HIGH")
        directions = Counter(row.direction.upper() for row in qualified)
        regimes = Counter(row.regime for row in qualified)
        if len(directions) < 2:
            warnings.append("DIRECTION_COVERAGE_SINGLE_SIDED")
        if len(regimes) < 2:
            warnings.append("REGIME_COVERAGE_LIMITED")
        return StabilityReport(
            state="READY" if not warnings else "READY_WITH_WARNINGS",
            n=n,
            windows=tuple(built),
            mean_dispersion=round(dispersion, 8),
            positive_window_fraction=round(positive_fraction, 8),
            direction_coverage=dict(sorted(directions.items())),
            regime_coverage=dict(sorted(regimes.items())),
            warnings=tuple(sorted(warnings)),
            method="CHRONOLOGICAL_WINDOWS_V1",
        )


@dataclass(frozen=True)
class MultipleComparisonItem:
    candidate: str
    raw_p_value: float
    adjusted_p_value: float
    rejected: bool
    rank: int


@dataclass(frozen=True)
class MultipleComparisonReport:
    state: str
    alpha: float
    hypothesis_count: int
    items: tuple[MultipleComparisonItem, ...]
    method: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HolmBonferroniController:
    """QBP-3 family-wise error control for externally computed p-values."""

    def evaluate(
        self,
        p_values: Mapping[str, float],
        *,
        alpha: float = 0.05,
        minimum_hypotheses: int = 1,
    ) -> MultipleComparisonReport:
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be between 0 and 1")
        checked: list[tuple[str, float]] = []
        for candidate, value in p_values.items():
            p = float(value)
            if not math.isfinite(p) or not 0.0 <= p <= 1.0:
                raise ValueError(f"invalid p-value for {candidate}")
            checked.append((str(candidate), p))
        checked.sort(key=lambda item: (item[1], item[0]))
        m = len(checked)
        if m < minimum_hypotheses:
            return MultipleComparisonReport("LOCKED_NO_HYPOTHESES", alpha, m, (), "HOLM_BONFERRONI_V1")
        running_max = 0.0
        adjusted: list[float] = []
        for index, (_, p) in enumerate(checked):
            raw_adjusted = min(1.0, (m - index) * p)
            running_max = max(running_max, raw_adjusted)
            adjusted.append(running_max)
        items = tuple(
            MultipleComparisonItem(candidate, p, round(adjusted[index], 10), adjusted[index] <= alpha, index + 1)
            for index, (candidate, p) in enumerate(checked)
        )
        return MultipleComparisonReport("READY", alpha, m, items, "HOLM_BONFERRONI_V1")


@dataclass(frozen=True)
class QBP3ValidationReport:
    schema: str
    generated_at: str
    state: str
    qualified_outcomes: int
    dataset_sha256: str
    bootstrap: dict[str, Any]
    stability: dict[str, Any]
    multiple_comparison: dict[str, Any]
    capabilities: dict[str, bool]
    blockers: tuple[str, ...]
    authority_granted: bool
    production_or_execution_authority: bool
    self_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class QuantumStatisticalValidationService:
    """QBP-3 coordinator. Unlocks research diagnostics at 300 outcomes only."""

    def evaluate(
        self,
        rows: Iterable[UnifiedOutcome],
        *,
        candidate_p_values: Mapping[str, float] | None = None,
        bootstrap_iterations: int = 2000,
    ) -> QBP3ValidationReport:
        qualification = OutcomeQualificationEngine().evaluate(rows)
        qualified = [row for row in qualification.records if row.status == "QUALIFIED"]
        values = [float(row.realized_r) for row in qualified if row.realized_r is not None]
        bootstrap = DeterministicBootstrapValidator().evaluate(
            values, dataset_sha256=qualification.dataset_sha256, iterations=bootstrap_iterations
        )
        stability = ChronologicalStabilityValidator().evaluate(qualification.records)
        multiple = HolmBonferroniController().evaluate(candidate_p_values or {}, minimum_hypotheses=1)
        count = qualification.qualified
        capabilities = {
            "bootstrap": count >= 300,
            "stability": count >= 300,
            "multiple_comparison": count >= 300 and bool(candidate_p_values),
        }
        blockers: list[str] = []
        if count < 300:
            blockers.append(f"QUALIFIED_OUTCOMES_BELOW_300:{count}")
        if qualification.pending_review:
            blockers.append(f"PENDING_REVIEW_OUTCOMES:{qualification.pending_review}")
        if not candidate_p_values:
            blockers.append("MULTIPLE_COMPARISON_P_VALUES_MISSING")
        blockers.extend(f"STABILITY_WARNING:{warning}" for warning in stability.warnings)
        state = "QBP3_STATISTICAL_VALIDATION_READY" if all(capabilities.values()) and not blockers else "QBP3_LOCKED_OR_REVIEW_REQUIRED"
        payload = {
            "schema": "DVS_QBP3_STATISTICAL_VALIDATION_V1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "state": state,
            "qualified_outcomes": count,
            "dataset_sha256": qualification.dataset_sha256,
            "bootstrap": bootstrap.to_dict(),
            "stability": stability.to_dict(),
            "multiple_comparison": multiple.to_dict(),
            "capabilities": capabilities,
            "blockers": tuple(blockers),
            "authority_granted": False,
            "production_or_execution_authority": False,
        }
        return QBP3ValidationReport(**payload, self_sha256=_sha256(payload))


@dataclass(frozen=True)
class GovernanceReviewItem:
    name: str
    passed: bool
    evidence: str


@dataclass(frozen=True)
class QBP4HandoverReview:
    schema: str
    generated_at: str
    state: str
    qualified_outcomes: int
    review_items: tuple[GovernanceReviewItem, ...]
    human_signoff_required: bool
    paper_authority_handover_eligible: bool
    paper_authority_handover_granted: bool
    authority_granted: bool
    production_or_execution_authority: bool
    blockers: tuple[str, ...]
    evidence_bundle_sha256: str
    self_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class QuantumGovernanceHandoverService:
    """QBP-4 review gate.

    This service can establish review eligibility at 500 qualified outcomes.
    It never grants paper, production, recommendation, or execution authority.
    Human governance sign-off remains an external mandatory action.
    """

    def evaluate(self, qbp3: QBP3ValidationReport) -> QBP4HandoverReview:
        count = qbp3.qualified_outcomes
        items = (
            GovernanceReviewItem("MINIMUM_500_QUALIFIED_OUTCOMES", count >= 500, str(count)),
            GovernanceReviewItem("QBP3_VALIDATION_READY", qbp3.state == "QBP3_STATISTICAL_VALIDATION_READY", qbp3.self_sha256),
            GovernanceReviewItem("BOOTSTRAP_READY", qbp3.bootstrap.get("state") == "READY", str(qbp3.bootstrap.get("state"))),
            GovernanceReviewItem("STABILITY_CLEAR", qbp3.stability.get("state") == "READY", str(qbp3.stability.get("state"))),
            GovernanceReviewItem("MULTIPLE_COMPARISON_READY", qbp3.multiple_comparison.get("state") == "READY", str(qbp3.multiple_comparison.get("state"))),
            GovernanceReviewItem("AUTHORITY_REMAINS_LOCKED", not qbp3.authority_granted and not qbp3.production_or_execution_authority, "false/false"),
        )
        blockers = tuple(item.name for item in items if not item.passed)
        eligible = not blockers
        state = "QBP4_HUMAN_GOVERNANCE_REVIEW_ELIGIBLE" if eligible else "QBP4_NOT_ELIGIBLE"
        evidence_payload = {"qbp3_sha256": qbp3.self_sha256, "items": [asdict(item) for item in items]}
        payload = {
            "schema": "DVS_QBP4_HANDOVER_REVIEW_V1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "state": state,
            "qualified_outcomes": count,
            "review_items": items,
            "human_signoff_required": True,
            "paper_authority_handover_eligible": eligible,
            "paper_authority_handover_granted": False,
            "authority_granted": False,
            "production_or_execution_authority": False,
            "blockers": blockers,
            "evidence_bundle_sha256": _sha256(evidence_payload),
        }
        serializable = {**payload, "review_items": [asdict(item) for item in items]}
        return QBP4HandoverReview(**payload, self_sha256=_sha256(serializable))
