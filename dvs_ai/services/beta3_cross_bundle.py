from __future__ import annotations

import math
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from dvs_ai.services.beta3_dataset_bundle import DatasetBundleVerifier
from dvs_ai.services.beta3_statistics_engine import DatasetBundleReader

DIAGNOSTIC_POLICY = {
    "diagnostic_policy_id": "beta3d.cross_bundle.v1",
    "relative_change_thresholds": {
        "minor_gte": 0.05,
        "moderate_gte": 0.15,
        "major_gte": 0.30,
    },
    "minimum_burn_in_level": "RESEARCH_CANDIDATE_ONLY",
    "lexicographic_order": (
        "burn_in_level:DESC",
        "coverage_ratio:DESC",
        "beta3b_quality_score:DESC",
        "record_count:DESC",
        "build_timestamp:DESC",
        "bundle_sha256:ASC",
    ),
}

BURN_IN_RANK = {
    "UNOBSERVABLE": 0,
    "DESCRIPTIVE_ONLY": 0,
    "RESEARCH_CANDIDATE_ONLY": 1,
    "VALIDATION_REVIEW_ELIGIBLE": 2,
    "BURN_IN_COMPLETE": 3,
}

COMPARISON_TYPE_A = "SAME_POLICY_SAME_EXTRACTOR"
COMPARISON_TYPE_B = "SAME_POLICY_DIFFERENT_EXTRACTOR"
COMPARISON_TYPE_C = "DIFFERENT_POLICY"


@dataclass(frozen=True)
class RegistryEntry:
    bundle_path: str
    dataset_id: str
    bundle_sha256: str
    parent_bundle_sha256: str | None
    build_timestamp: str
    decision_engine_checksum: str
    policy_scope_id: str
    policy_scope_hash: str
    extractor_checksum: str
    extractor_schema_version: str
    burn_in_level: str
    record_count: int
    coverage_ratio: float
    beta3b_quality_score: float
    hard_block: bool = False

    @property
    def policy_identity(self) -> tuple[str, str, str]:
        return (self.policy_scope_id, self.policy_scope_hash, self.decision_engine_checksum)

    @property
    def extraction_identity(self) -> tuple[str, str]:
        return (self.extractor_schema_version, self.extractor_checksum)


@dataclass(frozen=True)
class ExcludedEntry:
    bundle_path: str
    status: str
    verification_error_code: str
    verification_error_detail: tuple[str, ...]
    observed_at: str


@dataclass(frozen=True)
class RegistryResult:
    status: str
    verified_entries: tuple[RegistryEntry, ...]
    excluded_entries: tuple[ExcludedEntry, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComparisonResult:
    comparison_type: str
    comparison_state: str
    warnings: tuple[str, ...]
    raw_metrics: Mapping[str, Any]
    interpretations: Mapping[str, str | None]
    diagnostic_policy_id: str


@dataclass(frozen=True)
class TimelineResult:
    nodes: tuple[Mapping[str, Any], ...]
    edges: tuple[Mapping[str, Any], ...]
    anomalies: tuple[str, ...]


@dataclass(frozen=True)
class PromotionResult:
    promotion_mode: str
    comparative_evidence_available: bool
    promotion_cap: str
    recommendations: Mapping[str, str]
    ordered_candidates: tuple[str, ...]
    excluded: Mapping[str, tuple[str, ...]]


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _metric_delta(baseline: float | int, comparison: float | int) -> dict[str, float | None]:
    b = float(baseline)
    c = float(comparison)
    delta = c - b
    return {
        "baseline_value": b,
        "comparison_value": c,
        "delta": delta,
        "absolute_change": abs(delta),
        "relative_change": (delta / abs(b)) if b != 0 else (0.0 if c == 0 else None),
    }


def _interpret(relative_change: float | None, policy: Mapping[str, Any]) -> str:
    if relative_change is None:
        return "UNDEFINED_BASELINE"
    magnitude = abs(relative_change)
    thresholds = policy["relative_change_thresholds"]
    if magnitude >= thresholds["major_gte"]:
        return "MAJOR_SHIFT"
    if magnitude >= thresholds["moderate_gte"]:
        return "MODERATE_SHIFT"
    if magnitude >= thresholds["minor_gte"]:
        return "MINOR_SHIFT"
    return "STABLE"


class BundleRegistry:
    """Rebuildable, in-memory index. Verified bundles remain the sole source of truth."""

    def __init__(self, *, clock=None) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _derive_metrics(path: Path, manifest: Mapping[str, Any]) -> tuple[float, float]:
        """Read Beta 3B quality truth without recomputing a competing metric.

        ``coverage`` and ``quality_score`` are produced and sealed by the Beta 3B
        Dataset Builder in ``quality_report.json``.  Beta 3D is a derived index,
        so it must carry those values forward verbatim rather than derive a new
        feature-only score that ignores exclusions.
        """
        del manifest  # Kept in the signature for backward compatibility.
        data, errors = DatasetBundleReader().read(path)
        if data is None or errors:
            raise ValueError("BUNDLE_QUALITY_REPORT_UNREADABLE")

        report = data.quality_report
        try:
            coverage = float(report["coverage"])
            quality = float(report["quality_score"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("BUNDLE_QUALITY_REPORT_METRICS_INVALID") from exc

        if not (math.isfinite(coverage) and math.isfinite(quality)):
            raise ValueError("BUNDLE_QUALITY_REPORT_METRICS_INVALID")
        if not (0.0 <= coverage <= 1.0 and 0.0 <= quality <= 1.0):
            raise ValueError("BUNDLE_QUALITY_REPORT_METRICS_OUT_OF_RANGE")
        return coverage, quality

    def rebuild(self, bundle_paths: Iterable[str | os.PathLike[str]]) -> RegistryResult:
        verified: list[RegistryEntry] = []
        excluded: list[ExcludedEntry] = []
        seen_paths: set[str] = set()
        warnings: list[str] = []
        observed_at = self.clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        for raw_path in bundle_paths:
            path = Path(raw_path)
            normalized = str(path.resolve())
            if normalized in seen_paths:
                warnings.append("DUPLICATE_BUNDLE_PATH_IGNORED")
                continue
            seen_paths.add(normalized)
            result = DatasetBundleVerifier().verify(path)
            if not result.valid or not result.manifest:
                errors = tuple(result.errors or ("UNKNOWN_VERIFICATION_FAILURE",))
                excluded.append(ExcludedEntry(
                    bundle_path=str(path),
                    status="BUNDLE_VERIFICATION_FAILED_EXCLUDED",
                    verification_error_code=errors[0],
                    verification_error_detail=errors,
                    observed_at=observed_at,
                ))
                continue
            m = result.manifest
            try:
                coverage, quality = self._derive_metrics(path, m)
            except ValueError as exc:
                code = str(exc) or "BUNDLE_QUALITY_REPORT_METRICS_INVALID"
                excluded.append(ExcludedEntry(
                    bundle_path=str(path),
                    status="BUNDLE_VERIFICATION_FAILED_EXCLUDED",
                    verification_error_code=code,
                    verification_error_detail=(code,),
                    observed_at=observed_at,
                ))
                continue
            verified.append(RegistryEntry(
                bundle_path=str(path), dataset_id=str(m.get("dataset_id", "")),
                bundle_sha256=str(m.get("bundle_sha256", result.bundle_sha256 or "")),
                parent_bundle_sha256=m.get("parent_bundle_sha256"),
                build_timestamp=str(m.get("created_at", "")),
                decision_engine_checksum=str(m.get("decision_engine_checksum", "")),
                policy_scope_id=str(m.get("policy_scope_id", "")),
                policy_scope_hash=str(m.get("policy_scope_hash", "")),
                extractor_checksum=str(m.get("extractor_checksum", "")),
                extractor_schema_version=str(m.get("extractor_schema_version", "")),
                burn_in_level=str(m.get("burn_in_level", "UNOBSERVABLE")),
                record_count=int(m.get("record_count", 0)),
                coverage_ratio=coverage, beta3b_quality_score=quality,
            ))
        verified.sort(key=lambda item: item.bundle_sha256)
        excluded.sort(key=lambda item: item.bundle_path)
        status = "PASS" if not excluded else ("PARTIAL" if verified else "HARD_BLOCK")
        return RegistryResult(status, tuple(verified), tuple(excluded), tuple(sorted(set(warnings))))

    @staticmethod
    def stale_against(registry: RegistryResult, bundle_paths: Iterable[str | os.PathLike[str]]) -> bool:
        indexed = {str(Path(e.bundle_path).resolve()) for e in registry.verified_entries} | {str(Path(e.bundle_path).resolve()) for e in registry.excluded_entries}
        current = {str(Path(p).resolve()) for p in bundle_paths}
        return indexed != current


class BundleComparator:
    def __init__(self, *, diagnostic_policy: Mapping[str, Any] | None = None) -> None:
        self.policy = dict(diagnostic_policy or DIAGNOSTIC_POLICY)

    @staticmethod
    def classify(a: RegistryEntry, b: RegistryEntry) -> str:
        if a.policy_identity != b.policy_identity:
            return COMPARISON_TYPE_C
        if a.extraction_identity != b.extraction_identity:
            return COMPARISON_TYPE_B
        return COMPARISON_TYPE_A

    def compare(self, baseline: RegistryEntry, comparison: RegistryEntry) -> ComparisonResult:
        comparison_type = self.classify(baseline, comparison)
        warnings: list[str] = []
        observable = min(BURN_IN_RANK.get(baseline.burn_in_level, 0), BURN_IN_RANK.get(comparison.burn_in_level, 0)) >= BURN_IN_RANK["RESEARCH_CANDIDATE_ONLY"]
        if not observable:
            state = "COMPARISON_UNOBSERVABLE"
            warnings.append("LOW_CONFIDENCE_COMPARISON")
        elif comparison_type == COMPARISON_TYPE_B:
            state = "EXTRACTOR_CONFOUNDED_CHANGE"
            warnings.append("EXTRACTOR_CONFOUNDING_PRESENT")
        elif comparison_type == COMPARISON_TYPE_C:
            state = "CROSS_POLICY_CONTRAST"
            warnings.append("CROSS_POLICY_COMPARISON")
        else:
            state = "COMPARABLE"

        metrics = {
            "record_count": _metric_delta(baseline.record_count, comparison.record_count),
            "coverage_ratio": _metric_delta(baseline.coverage_ratio, comparison.coverage_ratio),
            "beta3b_quality_score": _metric_delta(baseline.beta3b_quality_score, comparison.beta3b_quality_score),
        }
        can_interpret = observable and comparison_type == COMPARISON_TYPE_A
        interpretations = {
            name: _interpret(metric["relative_change"], self.policy) if can_interpret else None
            for name, metric in metrics.items()
        }
        return ComparisonResult(comparison_type, state, tuple(warnings), metrics, interpretations, str(self.policy["diagnostic_policy_id"]))


class EvolutionTimeline:
    def build(self, entries: Sequence[RegistryEntry]) -> TimelineResult:
        by_hash = {e.bundle_sha256: e for e in entries}
        anomalies: set[str] = set()
        edges: list[dict[str, Any]] = []
        child_count: Counter[str] = Counter()
        for entry in entries:
            parent = entry.parent_bundle_sha256
            if not parent:
                continue
            if parent == entry.bundle_sha256:
                anomalies.add("LINEAGE_CYCLE")
                continue
            parent_entry = by_hash.get(parent)
            if parent_entry is None:
                anomalies.add("BROKEN_PARENT_REFERENCE")
                continue
            child_count[parent] += 1
            if parent_entry.policy_identity != entry.policy_identity:
                anomalies.add("CROSS_POLICY_LINEAGE")
            if parent_entry.extraction_identity != entry.extraction_identity:
                anomalies.add("EXTRACTOR_CHANGE_POINT")
            edges.append({"parent": parent, "child": entry.bundle_sha256})
        if any(count > 1 for count in child_count.values()):
            anomalies.add("FORKED_LINEAGE")
        if len(by_hash) != len(entries):
            anomalies.add("DUPLICATE_BUNDLE_IDENTITY")

        graph = defaultdict(list)
        for edge in edges:
            graph[edge["parent"]].append(edge["child"])
        visiting: set[str] = set(); visited: set[str] = set()
        def visit(node: str) -> None:
            if node in visiting:
                anomalies.add("LINEAGE_CYCLE"); return
            if node in visited: return
            visiting.add(node)
            for nxt in graph[node]: visit(nxt)
            visiting.remove(node); visited.add(node)
        for node in by_hash: visit(node)

        nodes = tuple({
            "bundle_sha256": e.bundle_sha256, "parent_bundle_sha256": e.parent_bundle_sha256,
            "build_timestamp": e.build_timestamp, "policy_identity": e.policy_identity,
            "extraction_identity": e.extraction_identity,
        } for e in sorted(entries, key=lambda x: (x.build_timestamp, x.bundle_sha256)))
        edges_sorted = tuple(sorted(edges, key=lambda x: (x["parent"], x["child"])))
        return TimelineResult(nodes, edges_sorted, tuple(sorted(anomalies)))


class PromotionRecommender:
    @staticmethod
    def _lineage_failures(entries: Sequence[RegistryEntry]) -> dict[str, tuple[str, ...]]:
        """Return entry-local lineage failures; never spread one bad branch to all bundles."""
        by_hash = {entry.bundle_sha256: entry for entry in entries}
        failures: dict[str, set[str]] = defaultdict(set)

        for entry in entries:
            parent_hash = entry.parent_bundle_sha256
            if not parent_hash:
                continue
            parent = by_hash.get(parent_hash)
            if parent is None:
                failures[entry.bundle_sha256].add("BROKEN_PARENT_REFERENCE")
                continue
            if parent.policy_identity != entry.policy_identity:
                failures[entry.bundle_sha256].add("CROSS_POLICY_LINEAGE")

        # Mark every node participating in a cycle, not unrelated branches.
        state: dict[str, int] = {}
        stack: list[str] = []
        stack_index: dict[str, int] = {}

        def visit(bundle_hash: str) -> None:
            marker = state.get(bundle_hash, 0)
            if marker == 2:
                return
            if marker == 1:
                cycle_start = stack_index[bundle_hash]
                for member in stack[cycle_start:]:
                    failures[member].add("LINEAGE_CYCLE")
                return
            state[bundle_hash] = 1
            stack_index[bundle_hash] = len(stack)
            stack.append(bundle_hash)
            parent_hash = by_hash[bundle_hash].parent_bundle_sha256
            if parent_hash in by_hash:
                visit(parent_hash)
            stack.pop()
            stack_index.pop(bundle_hash, None)
            state[bundle_hash] = 2

        for bundle_hash in by_hash:
            visit(bundle_hash)
        return {key: tuple(sorted(value)) for key, value in failures.items()}

    @staticmethod
    def _constraints(entry: RegistryEntry, lineage_failures: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
        reasons: list[str] = []
        if entry.hard_block:
            reasons.append("HARD_BLOCK_PRESENT")
        if BURN_IN_RANK.get(entry.burn_in_level, 0) < BURN_IN_RANK["RESEARCH_CANDIDATE_ONLY"]:
            reasons.append("BURN_IN_BELOW_MINIMUM")
        if entry.coverage_ratio <= 0:
            reasons.append("COVERAGE_FLOOR_NOT_MET")
        if entry.beta3b_quality_score <= 0:
            reasons.append("QUALITY_FLOOR_NOT_MET")
        if lineage_failures.get(entry.bundle_sha256):
            reasons.append("LINEAGE_NOT_VALID")
            reasons.extend(lineage_failures[entry.bundle_sha256])
        return tuple(sorted(set(reasons)))

    @staticmethod
    def _dominates(a: RegistryEntry, b: RegistryEntry) -> bool:
        av = (BURN_IN_RANK.get(a.burn_in_level, 0), a.coverage_ratio, a.beta3b_quality_score, a.record_count)
        bv = (BURN_IN_RANK.get(b.burn_in_level, 0), b.coverage_ratio, b.beta3b_quality_score, b.record_count)
        return all(x >= y for x, y in zip(av, bv)) and any(x > y for x, y in zip(av, bv))

    @staticmethod
    def _lex_key(e: RegistryEntry) -> tuple[Any, ...]:
        # DESC fields are negated. ISO-8601 UTC timestamps sort lexically.
        inverse_timestamp = "".join(chr(0x10FFFF - ord(c)) for c in e.build_timestamp)
        return (
            -BURN_IN_RANK.get(e.burn_in_level, 0),
            -e.coverage_ratio,
            -e.beta3b_quality_score,
            -e.record_count,
            inverse_timestamp,
            e.bundle_sha256,
        )

    @staticmethod
    def _cohort_key(entry: RegistryEntry) -> tuple[Any, ...]:
        return (entry.policy_identity, entry.extraction_identity)

    def recommend(self, entries: Sequence[RegistryEntry], timeline: TimelineResult | None = None) -> PromotionResult:
        # timeline remains part of the public API/report, but eligibility is computed
        # per entry so an invalid branch cannot poison an unrelated valid branch.
        timeline = timeline or EvolutionTimeline().build(entries)
        lineage_failures = self._lineage_failures(entries)
        excluded: dict[str, tuple[str, ...]] = {}
        eligible: list[RegistryEntry] = []
        for entry in entries:
            reasons = self._constraints(entry, lineage_failures)
            if reasons:
                excluded[entry.bundle_sha256] = reasons
            else:
                eligible.append(entry)

        cohorts: dict[tuple[Any, ...], list[RegistryEntry]] = defaultdict(list)
        for entry in eligible:
            cohorts[self._cohort_key(entry)].append(entry)

        comparative_cohorts = {key: group for key, group in cohorts.items() if len(group) >= 2}
        comparative = bool(comparative_cohorts)
        mode = "COMPARATIVE_PROMOTION" if comparative else "ABSOLUTE_ELIGIBILITY_FALLBACK"
        cap = "TRAINING_CANDIDATE" if comparative else "ELIGIBLE_CANDIDATE"

        recommendations: dict[str, str] = {sha: "REJECTED" for sha in excluded}
        for item in eligible:
            recommendations[item.bundle_sha256] = "ELIGIBLE_CANDIDATE"

        ordered: list[RegistryEntry] = []
        # Rank only within same-policy/same-extractor cohorts. Never compare or
        # select a winner across different policy or extraction identities.
        for cohort_key in sorted(cohorts, key=repr):
            group = cohorts[cohort_key]
            frontier = [
                item for item in group
                if not any(self._dominates(other, item) for other in group if other is not item)
            ]
            cohort_ordered = sorted(frontier, key=self._lex_key)
            ordered.extend(cohort_ordered)
            if len(group) >= 2 and cohort_ordered:
                recommendations[cohort_ordered[0].bundle_sha256] = "TRAINING_CANDIDATE"
                for item in cohort_ordered[1:]:
                    recommendations[item.bundle_sha256] = "RECOMMENDED"

        return PromotionResult(
            mode,
            comparative,
            cap,
            recommendations,
            tuple(e.bundle_sha256 for e in ordered),
            excluded,
        )


class CrossBundleDiagnosticsEngine:
    def __init__(self, *, diagnostic_policy: Mapping[str, Any] | None = None) -> None:
        self.registry = BundleRegistry()
        self.comparator = BundleComparator(diagnostic_policy=diagnostic_policy)
        self.timeline = EvolutionTimeline()
        self.promotion = PromotionRecommender()

    def run(self, bundle_paths: Iterable[str | os.PathLike[str]]) -> Mapping[str, Any]:
        registry = self.registry.rebuild(bundle_paths)
        timeline = self.timeline.build(registry.verified_entries)
        comparisons = []
        entries = registry.verified_entries
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                left, right = entries[i], entries[j]
                baseline, comparison = sorted(
                    (left, right), key=lambda entry: (entry.build_timestamp, entry.bundle_sha256)
                )
                comparisons.append(self.comparator.compare(baseline, comparison))
        promotion = self.promotion.recommend(entries, timeline)
        return {
            "report_schema_version": "beta3d.cross_bundle.report.v1",
            "diagnostic_policy": self.comparator.policy,
            "registry": registry,
            "timeline": timeline,
            "comparisons": tuple(comparisons),
            "promotion": promotion,
            "release_eligible": registry.status != "HARD_BLOCK",
        }
