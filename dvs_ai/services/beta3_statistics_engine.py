from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any, Mapping

from dvs_ai.services.beta3_dataset_bundle import DatasetBundleVerifier

DIAGNOSTIC_POLICY = {
    "policy_id": "beta3c.diagnostics.v1",
    "outlier_method": "IQR_1_5",
    "outlier_multiplier": 1.5,
    "outlier_rate_thresholds": {"low_gt": 0.0, "elevated_gte": 0.01, "high_gte": 0.05},
    "outcome_majority_rate_thresholds": {"mild_gte": 0.60, "moderate_gte": 0.70, "severe_gte": 0.80},
}
FORBIDDEN_MISSINGNESS_LABELS = {"MCAR", "MAR", "MNAR"}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


@dataclass(frozen=True)
class BundleData:
    path: Path
    manifest: Mapping[str, Any]
    dataset_rows: tuple[Mapping[str, Any], ...]
    exclusions: tuple[Mapping[str, Any], ...]
    quality_report: Mapping[str, Any]
    lineage_rows: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class StatisticsRunResult:
    status: str
    release_eligible: bool
    hard_block_errors: tuple[str, ...]
    soft_block_reasons: tuple[str, ...]
    report: Mapping[str, Any] | None


class DatasetBundleReader:
    """Reads exactly one verified Beta 3B bundle; never reads databases."""

    def read(self, bundle_path: str | os.PathLike[str]) -> tuple[BundleData | None, tuple[str, ...]]:
        if isinstance(bundle_path, (list, tuple, set, dict)):
            return None, ("MULTI_BUNDLE_INPUT_NOT_ALLOWED",)
        path = Path(bundle_path)
        verified = DatasetBundleVerifier().verify(path)
        if not verified.valid:
            return None, tuple(f"BUNDLE_VERIFY:{e}" for e in verified.errors)
        try:
            data = BundleData(
                path=path,
                manifest=verified.manifest or {},
                dataset_rows=tuple(_read_jsonl(path / "training_dataset.jsonl")),
                exclusions=tuple(_read_jsonl(path / "exclusions.jsonl")),
                quality_report=_read_json(path / "quality_report.json"),
                lineage_rows=tuple(_read_jsonl(path / "lineage_index.jsonl")),
            )
        except (OSError, json.JSONDecodeError):
            return None, ("BUNDLE_CONTENT_UNREADABLE",)
        return data, ()


class StatisticsEngine:
    def __init__(self, *, diagnostic_policy: Mapping[str, Any] | None = None) -> None:
        self.policy = dict(diagnostic_policy or DIAGNOSTIC_POLICY)

    @staticmethod
    def _self_consistency(data: BundleData) -> list[str]:
        errors: list[str] = []
        manifest = data.manifest
        expected_engine = manifest.get("decision_engine_checksum")
        expected_policy = manifest.get("policy_scope_hash")
        for row in data.dataset_rows:
            if row.get("decision_engine_checksum") != expected_engine:
                errors.append("DATASET_ENGINE_CHECKSUM_MISMATCH")
            if row.get("policy_scope_hash") != expected_policy:
                errors.append("DATASET_POLICY_SCOPE_MISMATCH")
        for row in data.lineage_rows:
            if row.get("decision_engine_checksum") != expected_engine:
                errors.append("LINEAGE_ENGINE_CHECKSUM_MISMATCH")
            if row.get("policy_scope_hash") != expected_policy:
                errors.append("LINEAGE_POLICY_SCOPE_MISMATCH")
        qualities = [q for row in data.dataset_rows for q in (row.get("feature_quality") or {}).values()]
        feature_count = sum(len(row.get("features") or {}) for row in data.dataset_rows)
        valid_count = sum(1 for q in qualities if q == "VALID")
        qr = data.quality_report
        if qr.get("feature_count") != feature_count or qr.get("valid_feature_count") != valid_count:
            errors.append("QUALITY_AGGREGATION_MISMATCH")
        expected_completeness = valid_count / max(1, feature_count)
        try:
            observed = float(qr.get("feature_completeness"))
            if not math.isclose(observed, expected_completeness, rel_tol=1e-12, abs_tol=1e-12):
                errors.append("QUALITY_AGGREGATION_MISMATCH")
        except (TypeError, ValueError):
            errors.append("QUALITY_AGGREGATION_MISMATCH")
        return sorted(set(errors))

    def _numeric_feature(self, name: str, rows: tuple[Mapping[str, Any], ...]) -> dict[str, Any]:
        all_values = [(row.get("features") or {}).get(name) for row in rows]
        values = [float(v) for v in all_values if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))]
        missing_count = len(all_values) - len(values)
        q1, q3 = _percentile(values, .25), _percentile(values, .75)
        result: dict[str, Any] = {
            "count": len(all_values), "valid_count": len(values), "missing_count": missing_count,
            "mean": mean(values) if values else None, "median": median(values) if values else None,
            "std_population": pstdev(values) if values else None,
            "min": min(values) if values else None, "max": max(values) if values else None,
            "p25": q1, "p50": _percentile(values, .5), "p75": q3,
        }
        if not values:
            result["outlier"] = {"state": "UNOBSERVABLE", "outlier_count": 0, "outlier_rate": 0.0}
            return result
        iqr = float(q3 - q1)  # type: ignore[operator]
        if iqr == 0:
            outside = [v for v in values if v != q1]
            result["outlier"] = {
                "state": "ZERO_IQR", "iqr": 0.0, "lower_fence": q1, "upper_fence": q3,
                "outside_constant_core_count": len(outside), "outlier_count": 0, "outlier_rate": 0.0,
            }
            return result
        lower = float(q1) - float(self.policy["outlier_multiplier"]) * iqr
        upper = float(q3) + float(self.policy["outlier_multiplier"]) * iqr
        outliers = [v for v in values if v < lower or v > upper]
        rate = len(outliers) / len(values)
        thresholds = self.policy["outlier_rate_thresholds"]
        if rate == 0:
            label = "NO_FLAG"
        elif rate >= thresholds["high_gte"]:
            label = "HIGH_OUTLIER_RATE"
        elif rate >= thresholds["elevated_gte"]:
            label = "ELEVATED_OUTLIER_RATE"
        else:
            label = "LOW_OUTLIER_RATE"
        result["outlier"] = {
            "state": label, "iqr": iqr, "lower_fence": lower, "upper_fence": upper,
            "outlier_count": len(outliers), "outlier_rate": rate,
            "minimum_outlier": min(outliers) if outliers else None,
            "maximum_outlier": max(outliers) if outliers else None,
        }
        return result

    @staticmethod
    def _categorical_feature(name: str, rows: tuple[Mapping[str, Any], ...]) -> dict[str, Any]:
        values = [(row.get("features") or {}).get(name) for row in rows]
        present = [v for v in values if v is not None]
        counts = Counter(str(v) for v in present)
        total = len(present)
        return {
            "count": len(values), "valid_count": total, "missing_count": len(values)-total,
            "category_count": len(counts),
            "frequencies": {k: counts[k] for k in sorted(counts)},
            "proportions": {k: counts[k] / total for k in sorted(counts)} if total else {},
        }

    @staticmethod
    def _outcome_balance(rows: tuple[Mapping[str, Any], ...], policy: Mapping[str, Any]) -> dict[str, Any]:
        counts = Counter(row.get("outcome_status") for row in rows)
        invalid = sorted(str(k) for k in counts if k not in {"WIN", "LOSS"})
        total = sum(counts.values())
        win = counts.get("WIN", 0); loss = counts.get("LOSS", 0)
        majority = max(win, loss)
        minority = min(win, loss)
        majority_rate = majority / total if total else 0.0
        t = policy["outcome_majority_rate_thresholds"]
        if majority_rate >= t["severe_gte"]:
            label = "SEVERE_IMBALANCE"
        elif majority_rate >= t["moderate_gte"]:
            label = "MODERATE_IMBALANCE"
        elif majority_rate >= t["mild_gte"]:
            label = "MILD_IMBALANCE"
        else:
            label = "BALANCED"
        return {
            "counts": {"WIN": win, "LOSS": loss}, "rates": {"WIN": win/total if total else 0.0, "LOSS": loss/total if total else 0.0},
            "majority_rate": majority_rate, "minority_rate": minority/total if total else 0.0,
            "majority_to_minority_ratio": (majority/minority if minority else None),
            "absolute_rate_gap": abs(win-loss)/total if total else 0.0,
            "state": label, "invalid_outcomes": invalid,
        }

    @staticmethod
    def _missingness(data: BundleData, feature_names: list[str]) -> dict[str, Any]:
        by_design = set(data.manifest.get("features_missing_by_design", []))
        exclusions_by_reason = Counter(str(e.get("reason", "UNDECLARED")) for e in data.exclusions)
        features: dict[str, Any] = {}
        for name in feature_names:
            affected = [row.get("dataset_row_id") for row in data.dataset_rows if (row.get("features") or {}).get(name) is None]
            if not affected:
                label = "NOT_MISSING"
            elif name in by_design:
                label = "MISSING_BY_DESIGN"
            else:
                label = "MISSING_WITHOUT_DECLARED_REASON"
            features[name] = {"classification": label, "missing_count": len(affected), "affected_rows": affected}
        return {
            "features": features,
            "eligibility_exclusions": {"classification": "MISSING_BY_ELIGIBILITY_EXCLUSION", "counts_by_reason": dict(sorted(exclusions_by_reason.items()))},
        }

    def run(
        self,
        bundle_path: str | os.PathLike[str],
        *,
        verify_current_engine: bool = True,
        current_engine_path: str | os.PathLike[str] | None = None,
    ) -> StatisticsRunResult:
        data, read_errors = DatasetBundleReader().read(bundle_path)
        if read_errors or data is None:
            return StatisticsRunResult("HARD_BLOCK", False, read_errors, (), None)
        hard = self._self_consistency(data)
        invalid_outcomes = sorted({str(r.get("outcome_status")) for r in data.dataset_rows if r.get("outcome_status") not in {"WIN", "LOSS"}})
        if invalid_outcomes:
            hard.append("NON_BINARY_OUTCOME_IN_DATASET")
        if hard:
            return StatisticsRunResult("HARD_BLOCK", False, tuple(sorted(set(hard))), (), None)

        soft: list[str] = []
        attestation: dict[str, Any]
        if not verify_current_engine:
            soft.append("RUNTIME_ATTESTATION_NOT_REQUESTED")
            attestation = {"state": "NOT_REQUESTED", "current_checksum": None}
        else:
            path = Path(current_engine_path) if current_engine_path else Path(__file__).parents[1] / "engines" / "decision_engine.py"
            if not path.is_file():
                soft.append("CURRENT_ENGINE_FILE_UNAVAILABLE")
                attestation = {"state": "CURRENT_ENGINE_FILE_UNAVAILABLE", "current_checksum": None}
            else:
                current = _file_sha256(path)
                expected = data.manifest.get("decision_engine_checksum")
                state = "MATCH" if current == expected else "MISMATCH"
                if state == "MISMATCH":
                    soft.append("CURRENT_DECISION_ENGINE_MISMATCH")
                attestation = {"state": state, "current_checksum": current, "expected_checksum": expected, "scope": str(path)}

        feature_names = sorted({name for row in data.dataset_rows for name in (row.get("features") or {})})
        numeric: dict[str, Any] = {}
        categorical: dict[str, Any] = {}
        coverage: dict[str, Any] = {}
        quality_counts: dict[str, Any] = {}
        for name in feature_names:
            raw = [(row.get("features") or {}).get(name) for row in data.dataset_rows]
            numeric_values = [v for v in raw if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if numeric_values and len(numeric_values) == len([v for v in raw if v is not None]):
                numeric[name] = self._numeric_feature(name, data.dataset_rows)
            else:
                categorical[name] = self._categorical_feature(name, data.dataset_rows)
            present = sum(1 for v in raw if v is not None)
            coverage[name] = {"present_count": present, "missing_count": len(raw)-present, "coverage_rate": present/len(raw) if raw else 0.0}
            q = Counter((row.get("feature_quality") or {}).get(name, "MISSING") for row in data.dataset_rows)
            quality_counts[name] = {k: q[k] for k in sorted(q)}

        report = {
            "report_schema_version": "beta3c.statistics.v1",
            "diagnostic_policy": self.policy,
            "dataset_identity": {
                "dataset_id": data.manifest.get("dataset_id"), "bundle_sha256": data.manifest.get("bundle_sha256"),
                "policy_scope_id": data.manifest.get("policy_scope_id"), "policy_scope_hash": data.manifest.get("policy_scope_hash"),
                "decision_engine_checksum": data.manifest.get("decision_engine_checksum"), "record_count": len(data.dataset_rows),
                "burn_in_level": data.manifest.get("burn_in_level"),
            },
            "runtime_environment_attestation": attestation,
            "descriptive_statistics": numeric,
            "categorical_feature_distribution": categorical,
            "coverage": coverage,
            "missingness": self._missingness(data, feature_names),
            "feature_quality_aggregation": quality_counts,
            "outcome_balance": self._outcome_balance(data.dataset_rows, self.policy),
            "release_eligible": not soft,
            "release_gate": "PASS" if not soft else "SOFT_BLOCK",
            "soft_block_reasons": sorted(set(soft)),
        }
        return StatisticsRunResult("PASS" if not soft else "SOFT_BLOCK", not soft, (), tuple(sorted(set(soft))), report)
