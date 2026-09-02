from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from dvs_ai.services.quantum_explainability.foundation import canonical_hash, canonical_json, verify_dataset_bundle
from dvs_ai.services.quantum_counterfactual.ablation import AblationStudy, AssociationClass, HistoricalAblationEngine
from dvs_ai.services.quantum_counterfactual.replay import HistoricalReplayEngine, ReplayState

UNCERTAINTY_SCHEMA_VERSION = "dvs-quantum-uncertainty-v1"
UNCERTAINTY_MANIFEST_VERSION = "dvs-quantum-uncertainty-manifest-v1"


class UncertaintyState(str, Enum):
    COMPLETED = "COMPLETED"
    UNOBSERVABLE = "UNOBSERVABLE"
    INVALID_STUDY = "INVALID_STUDY"
    REPLAY_BLOCKED = "REPLAY_BLOCKED"
    DATASET_INTEGRITY_BLOCKED = "DATASET_INTEGRITY_BLOCKED"


@dataclass(frozen=True)
class ConfidenceInterval:
    confidence_level: float
    lower: float | None
    upper: float | None
    point_estimate: float | None
    method: str


@dataclass(frozen=True)
class CoverageSummary:
    raw_n: int
    resolved_n: int
    observed_n: int
    missing_n: int
    cluster_n: int
    effective_n: float
    symbol_n: int
    regime_n: int
    temporal_fold_n: int


@dataclass(frozen=True)
class AssociationDiagnostics:
    observed_mean_r: float | None
    missing_mean_r: float | None
    delta_mean_r: float | None
    confidence_interval: ConfidenceInterval
    sign_stability: float | None
    association_class: AssociationClass
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class UncertaintyResult:
    state: UncertaintyState
    study_id: str
    target_field: str
    replay_state: str
    coverage: CoverageSummary
    diagnostics: AssociationDiagnostics
    bootstrap_iterations: int
    random_seed: int
    limitations: tuple[str, ...]
    violations: tuple[str, ...]
    manifest: Mapping[str, Any]
    optimizer_allowed: bool = False
    recommendation_allowed: bool = False
    shadow_apply_allowed: bool = False
    main_write_authority: bool = False

    def export(self, output_dir: str | Path) -> tuple[Path, Path]:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        result_path = root / f"quantum_uncertainty_{self.study_id}.json"
        payload_obj = asdict(self)
        payload_obj.pop("manifest", None)
        payload = canonical_json(payload_obj).encode("utf-8")
        result_path.write_bytes(payload)

        manifest = dict(self.manifest)
        manifest["result_file"] = result_path.name
        manifest["result_file_sha256"] = hashlib.sha256(payload).hexdigest()
        unsigned = canonical_json(manifest).encode("utf-8")
        manifest["self_sha256"] = hashlib.sha256(unsigned).hexdigest()
        manifest_path = root / f"quantum_uncertainty_{self.study_id}.manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return result_path, manifest_path


class UncertaintyEstimator:
    """Cluster-aware, read-only association diagnostics for historical evidence.

    The estimator compares resolved historical outcomes where an evidence field is
    observed versus missing. This is an association diagnostic only. It never
    re-runs the Decision Engine, mutates a TradePlan, creates recommendations, or
    writes MAIN/SHADOW state.
    """

    def __init__(
        self,
        dataset_path: str | Path,
        dataset_manifest_path: str | Path,
        *,
        bootstrap_iterations: int = 2000,
        confidence_level: float = 0.95,
        random_seed: int = 4303,
        minimum_effective_n: float = 30.0,
        robust_effective_n: float = 100.0,
        minimum_sign_stability: float = 0.80,
        robust_sign_stability: float = 0.90,
    ) -> None:
        if bootstrap_iterations < 100:
            raise ValueError("bootstrap_iterations must be >= 100")
        if not 0.5 < confidence_level < 1.0:
            raise ValueError("confidence_level must be between 0.5 and 1.0")
        self.dataset_path = Path(dataset_path)
        self.dataset_manifest_path = Path(dataset_manifest_path)
        self.bootstrap_iterations = int(bootstrap_iterations)
        self.confidence_level = float(confidence_level)
        self.random_seed = int(random_seed)
        self.minimum_effective_n = float(minimum_effective_n)
        self.robust_effective_n = float(robust_effective_n)
        self.minimum_sign_stability = float(minimum_sign_stability)
        self.robust_sign_stability = float(robust_sign_stability)

    def run(self, study: AblationStudy) -> UncertaintyResult:
        study = study.normalized()
        valid, dataset_manifest, detail = verify_dataset_bundle(self.dataset_path, self.dataset_manifest_path)
        if not valid:
            return self._blocked(study, UncertaintyState.DATASET_INTEGRITY_BLOCKED, detail)

        violations = HistoricalAblationEngine._validate_study(study)
        if violations:
            return self._invalid(study, violations, dataset_manifest)

        replay = HistoricalReplayEngine(self.dataset_path, self.dataset_manifest_path).build()
        if replay.state != ReplayState.VERIFIED:
            return self._blocked(
                study,
                UncertaintyState.REPLAY_BLOCKED,
                f"historical replay state is {replay.state.value}",
                dataset_manifest,
                replay_state=replay.state.value,
            )

        verified_ids = {record.sample_id for record in replay.records if record.replay_state == ReplayState.VERIFIED.value}
        rows = [row for row in self._read_rows() if str(row.get("sample_id") or "") in verified_ids]
        resolved = [row for row in rows if self._resolved_r(row) is not None]
        coverage = self._coverage(resolved, study.target_field)

        observed = [row for row in resolved if self._is_observed(row.get(study.target_field))]
        missing = [row for row in resolved if not self._is_observed(row.get(study.target_field))]
        reasons: list[str] = []

        if not observed or not missing:
            reasons.append("BOTH_OBSERVED_AND_MISSING_COHORTS_REQUIRED")
        if coverage.effective_n < self.minimum_effective_n:
            reasons.append("EFFECTIVE_SAMPLE_SIZE_BELOW_MINIMUM")
        if coverage.cluster_n < 2:
            reasons.append("INSUFFICIENT_INDEPENDENT_CLUSTERS")

        observed_mean = self._mean_r(observed)
        missing_mean = self._mean_r(missing)
        delta = self._delta(observed_mean, missing_mean)
        if reasons:
            diagnostics = AssociationDiagnostics(
                observed_mean_r=observed_mean,
                missing_mean_r=missing_mean,
                delta_mean_r=delta,
                confidence_interval=ConfidenceInterval(self.confidence_level, None, None, delta, "cluster_bootstrap_percentile"),
                sign_stability=None,
                association_class=AssociationClass.UNOBSERVABLE,
                reasons=tuple(reasons),
            )
            return self._result(study, UncertaintyState.UNOBSERVABLE, replay.state.value, coverage, diagnostics, dataset_manifest, detail)

        distribution = self._cluster_bootstrap_delta(resolved, study.target_field)
        if not distribution:
            reasons.append("BOOTSTRAP_DISTRIBUTION_EMPTY")
            diagnostics = AssociationDiagnostics(
                observed_mean_r=observed_mean,
                missing_mean_r=missing_mean,
                delta_mean_r=delta,
                confidence_interval=ConfidenceInterval(self.confidence_level, None, None, delta, "cluster_bootstrap_percentile"),
                sign_stability=None,
                association_class=AssociationClass.UNOBSERVABLE,
                reasons=tuple(reasons),
            )
            return self._result(study, UncertaintyState.UNOBSERVABLE, replay.state.value, coverage, diagnostics, dataset_manifest, detail)

        alpha = (1.0 - self.confidence_level) / 2.0
        lower = self._percentile(distribution, alpha)
        upper = self._percentile(distribution, 1.0 - alpha)
        sign_stability = self._sign_stability(distribution, delta)
        association_class, class_reasons = self._classify(coverage, lower, upper, sign_stability)
        reasons.extend(class_reasons)
        diagnostics = AssociationDiagnostics(
            observed_mean_r=observed_mean,
            missing_mean_r=missing_mean,
            delta_mean_r=delta,
            confidence_interval=ConfidenceInterval(self.confidence_level, lower, upper, delta, "cluster_bootstrap_percentile"),
            sign_stability=sign_stability,
            association_class=association_class,
            reasons=tuple(reasons),
        )
        return self._result(study, UncertaintyState.COMPLETED, replay.state.value, coverage, diagnostics, dataset_manifest, detail)

    def _classify(self, coverage: CoverageSummary, lower: float, upper: float, stability: float) -> tuple[AssociationClass, tuple[str, ...]]:
        if lower <= 0.0 <= upper:
            return AssociationClass.INCONCLUSIVE, ("CONFIDENCE_INTERVAL_CROSSES_ZERO",)
        if stability < self.minimum_sign_stability:
            return AssociationClass.INCONCLUSIVE, ("SIGN_STABILITY_BELOW_MINIMUM",)
        robust = (
            coverage.effective_n >= self.robust_effective_n
            and stability >= self.robust_sign_stability
            and coverage.symbol_n >= 2
            and coverage.temporal_fold_n >= 3
        )
        if robust:
            return AssociationClass.ROBUST_ASSOCIATION, ("NON_CAUSAL_ROBUST_ASSOCIATION_CRITERIA_MET",)
        return AssociationClass.ASSOCIATED, ("NON_CAUSAL_ASSOCIATION_CRITERIA_MET",)

    def _cluster_bootstrap_delta(self, rows: Sequence[Mapping[str, Any]], target_field: str) -> list[float]:
        clusters: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            clusters.setdefault(self._cluster_id(row), []).append(row)
        keys = sorted(clusters)
        rng = random.Random(self.random_seed)
        values: list[float] = []
        for _ in range(self.bootstrap_iterations):
            sample: list[Mapping[str, Any]] = []
            for _ in keys:
                sample.extend(clusters[rng.choice(keys)])
            observed = [row for row in sample if self._is_observed(row.get(target_field))]
            missing = [row for row in sample if not self._is_observed(row.get(target_field))]
            delta = self._delta(self._mean_r(observed), self._mean_r(missing))
            if delta is not None and math.isfinite(delta):
                values.append(delta)
        values.sort()
        return values

    def _coverage(self, rows: Sequence[Mapping[str, Any]], target_field: str) -> CoverageSummary:
        observed_n = sum(self._is_observed(row.get(target_field)) for row in rows)
        cluster_ids = [self._cluster_id(row) for row in rows]
        cluster_n = len(set(cluster_ids))
        symbol_n = len({str(row.get("symbol") or "UNKNOWN") for row in rows})
        regime_n = len({str(row.get("regime") or row.get("market_regime") or "UNKNOWN") for row in rows})
        temporal_fold_n = len({self._temporal_fold(row) for row in rows})
        effective_n = self._effective_n(cluster_ids)
        return CoverageSummary(
            raw_n=len(rows),
            resolved_n=len(rows),
            observed_n=observed_n,
            missing_n=len(rows) - observed_n,
            cluster_n=cluster_n,
            effective_n=effective_n,
            symbol_n=symbol_n,
            regime_n=regime_n,
            temporal_fold_n=temporal_fold_n,
        )

    @staticmethod
    def _effective_n(cluster_ids: Sequence[str]) -> float:
        if not cluster_ids:
            return 0.0
        counts: dict[str, int] = {}
        for value in cluster_ids:
            counts[value] = counts.get(value, 0) + 1
        total = float(len(cluster_ids))
        concentration = sum((count / total) ** 2 for count in counts.values())
        inverse_concentration = (1.0 / concentration) if concentration else 0.0
        return round(min(total, float(len(counts)), inverse_concentration), 6)

    @staticmethod
    def _cluster_id(row: Mapping[str, Any]) -> str:
        explicit = str(row.get("market_event_cluster_id") or "").strip()
        if explicit:
            return explicit
        symbol = str(row.get("symbol") or "UNKNOWN")
        stamp = str(row.get("first_eligible_timestamp") or "UNKNOWN")
        day = stamp[:10] if len(stamp) >= 10 else stamp
        return f"{symbol}|{day}"

    @staticmethod
    def _temporal_fold(row: Mapping[str, Any]) -> str:
        stamp = str(row.get("first_eligible_timestamp") or "UNKNOWN")
        return stamp[:7] if len(stamp) >= 7 else stamp

    def _read_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for line_number, raw in enumerate(self.dataset_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError(f"dataset row {line_number} is not an object")
            rows.append(value)
        return rows

    @staticmethod
    def _resolved_r(row: Mapping[str, Any]) -> float | None:
        if str(row.get("outcome_status") or "").upper() not in {"WIN", "LOSS"}:
            return None
        value = row.get("realized_r")
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    @staticmethod
    def _is_observed(value: Any) -> bool:
        if value is None or value == "" or value == [] or value == {}:
            return False
        return not (isinstance(value, float) and math.isnan(value))

    @classmethod
    def _mean_r(cls, rows: Iterable[Mapping[str, Any]]) -> float | None:
        values = [value for row in rows if (value := cls._resolved_r(row)) is not None]
        return (sum(values) / len(values)) if values else None

    @staticmethod
    def _delta(left: float | None, right: float | None) -> float | None:
        return None if left is None or right is None else left - right

    @staticmethod
    def _percentile(values: Sequence[float], probability: float) -> float:
        if not values:
            raise ValueError("values cannot be empty")
        if len(values) == 1:
            return values[0]
        position = (len(values) - 1) * probability
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return values[lower]
        weight = position - lower
        return values[lower] * (1.0 - weight) + values[upper] * weight

    @staticmethod
    def _sign_stability(values: Sequence[float], point_estimate: float | None) -> float:
        if not values or point_estimate is None or point_estimate == 0:
            return 0.0
        same = sum((value > 0) == (point_estimate > 0) for value in values)
        return same / len(values)

    def _invalid(self, study: AblationStudy, violations: tuple[str, ...], dataset_manifest: Mapping[str, Any]) -> UncertaintyResult:
        coverage = CoverageSummary(0, 0, 0, 0, 0, 0.0, 0, 0, 0)
        diagnostics = AssociationDiagnostics(None, None, None, ConfidenceInterval(self.confidence_level, None, None, None, "not_run"), None, AssociationClass.UNOBSERVABLE, violations)
        return self._result(study, UncertaintyState.INVALID_STUDY, "NOT_RUN", coverage, diagnostics, dataset_manifest, "; ".join(violations), violations)

    def _blocked(self, study: AblationStudy, state: UncertaintyState, detail: str, dataset_manifest: Mapping[str, Any] | None = None, replay_state: str = "NOT_RUN") -> UncertaintyResult:
        coverage = CoverageSummary(0, 0, 0, 0, 0, 0.0, 0, 0, 0)
        diagnostics = AssociationDiagnostics(None, None, None, ConfidenceInterval(self.confidence_level, None, None, None, "not_run"), None, AssociationClass.UNOBSERVABLE, (detail,))
        return self._result(study, state, replay_state, coverage, diagnostics, dataset_manifest or {}, detail)

    def _result(self, study: AblationStudy, state: UncertaintyState, replay_state: str, coverage: CoverageSummary, diagnostics: AssociationDiagnostics, dataset_manifest: Mapping[str, Any], detail: str, violations: tuple[str, ...] = ()) -> UncertaintyResult:
        manifest = {
            "manifest_version": UNCERTAINTY_MANIFEST_VERSION,
            "schema_version": UNCERTAINTY_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "state": state.value,
            "study": asdict(study),
            "replay_state": replay_state,
            "dataset_file": self.dataset_path.name,
            "dataset_manifest_file": self.dataset_manifest_path.name,
            "dataset_sha256": dataset_manifest.get("dataset_sha256"),
            "dataset_manifest_self_sha256": dataset_manifest.get("self_sha256"),
            "bootstrap_iterations": self.bootstrap_iterations,
            "confidence_level": self.confidence_level,
            "random_seed": self.random_seed,
            "association_class": diagnostics.association_class.value,
            "causal_claim_allowed": False,
            "qg_contract": "QG-01..QG-16",
            "detail": detail,
            "safety_boundary": {
                "decision_engine_frozen": True,
                "decision_engine_reexecution": False,
                "trade_plan_mutation": False,
                "outcome_mutation": False,
                "optimizer_authority": False,
                "recommendation_authority": False,
                "shadow_write_authority": False,
                "main_write_authority": False,
            },
        }
        return UncertaintyResult(
            state=state,
            study_id=study.study_id,
            target_field=study.target_field,
            replay_state=replay_state,
            coverage=coverage,
            diagnostics=diagnostics,
            bootstrap_iterations=self.bootstrap_iterations,
            random_seed=self.random_seed,
            limitations=(
                "Historical association is not causation.",
                "Missingness may be informative and may reflect upstream data quality or regime effects.",
                "Cluster bootstrap uncertainty depends on the supplied or derived market-event clusters.",
                "No optimizer, recommendation, SHADOW write, MAIN write, or execution authority is granted.",
            ),
            violations=violations,
            manifest=manifest,
        )


def verify_uncertainty_bundle(result_path: str | Path, manifest_path: str | Path) -> tuple[bool, str]:
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"manifest unreadable: {exc}"
    expected_self = str(manifest.get("self_sha256") or "")
    unsigned = dict(manifest)
    unsigned.pop("self_sha256", None)
    if not expected_self or canonical_hash(unsigned) != expected_self:
        return False, "manifest self checksum mismatch"
    result = Path(result_path)
    if not result.exists():
        return False, "uncertainty result file missing"
    if manifest.get("result_file") != result.name:
        return False, "uncertainty result filename does not match manifest"
    if hashlib.sha256(result.read_bytes()).hexdigest() != str(manifest.get("result_file_sha256") or ""):
        return False, "uncertainty result checksum mismatch"
    try:
        payload = json.loads(result.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"uncertainty result unreadable: {exc}"
    forbidden = ("optimizer_allowed", "recommendation_allowed", "shadow_apply_allowed", "main_write_authority")
    if any(payload.get(field) for field in forbidden):
        return False, "forbidden authority enabled"
    if manifest.get("causal_claim_allowed") is not False:
        return False, "causal claim boundary missing"
    return True, "verified"
