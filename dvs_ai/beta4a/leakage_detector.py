from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from typing import Iterable, Mapping, Sequence

from .dataset_split import SplitArtifact
from .errors import Beta4AGateError


class LeakageSeverity(str, Enum):
    WARNING = "WARNING"
    HARD_BLOCK = "HARD_BLOCK"


class LeakageReportStatus(str, Enum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class LeakageRowEvidence:
    """Already-produced lineage and descriptive values consumed by M4.

    M4 never regenerates timestamps, labels, features, quality, coverage or
    burn-in. Callers must pass those lower-layer values without transformation.
    """

    dataset_row_id: str
    structural_group_id: str
    snapshot_timestamp: str | None
    first_eligible_evaluation_timestamp: str | None
    label_value: float | int | None = None
    feature_values: Mapping[str, float | int | None] | None = None

    def __post_init__(self) -> None:
        if not self.dataset_row_id:
            raise ValueError("dataset_row_id must be non-empty")
        if not self.structural_group_id:
            raise ValueError("structural_group_id must be non-empty")


@dataclass(frozen=True, slots=True)
class BundleRowMembership:
    dataset_row_id: str
    bundle_sha256: str

    def __post_init__(self) -> None:
        if not self.dataset_row_id or not self.bundle_sha256:
            raise ValueError("bundle membership fields must be non-empty")


@dataclass(frozen=True, slots=True)
class LeakageFinding:
    code: str
    severity: LeakageSeverity
    message: str
    dataset_row_ids: tuple[str, ...] = ()
    feature_name: str | None = None
    observed_value: float | None = None


@dataclass(frozen=True, slots=True)
class LeakageDetectionReport:
    report_id: str
    report_sha256: str
    split_sha256: str
    bundle_sha256: str
    feature_schema_identity: str | None
    status: LeakageReportStatus
    findings: tuple[LeakageFinding, ...]
    checked_row_count: int
    checked_feature_count: int

    @property
    def hard_blocks(self) -> tuple[LeakageFinding, ...]:
        return tuple(item for item in self.findings if item.severity is LeakageSeverity.HARD_BLOCK)

    @property
    def warnings(self) -> tuple[LeakageFinding, ...]:
        return tuple(item for item in self.findings if item.severity is LeakageSeverity.WARNING)


class LeakageDetector:
    """Structural leakage verifier for Beta 4A M4.

    This verifier only reads and compares already-produced evidence. It does not
    recompute lower-layer metrics or alter rows/features.
    """

    def detect(
        self,
        rows: Iterable[LeakageRowEvidence | Mapping[str, object]],
        *,
        split_artifact: SplitArtifact,
        bundle_sha256: str,
        bundle_memberships: Sequence[BundleRowMembership | Mapping[str, object]] = (),
        feature_schema_identity: str | None = None,
        suspicious_correlation_threshold: float = 0.98,
        minimum_correlation_pairs: int = 3,
    ) -> LeakageDetectionReport:
        if not bundle_sha256:
            raise ValueError("bundle_sha256 must be non-empty")
        if not 0.0 <= suspicious_correlation_threshold <= 1.0:
            raise ValueError("suspicious_correlation_threshold must be within [0, 1]")
        if minimum_correlation_pairs < 3:
            raise ValueError("minimum_correlation_pairs must be at least three")
        if split_artifact.source_bundle_sha256 != bundle_sha256:
            raise Beta4AGateError(
                "LEAKAGE_SOURCE_BUNDLE_MISMATCH",
                "split source bundle does not match leakage detector bundle",
            )

        normalized = tuple(self._coerce_row(row) for row in rows)
        self._verify_unique_rows(normalized)
        row_by_id = {row.dataset_row_id: row for row in normalized}
        split_ids = (
            split_artifact.train.dataset_row_ids
            + split_artifact.validation.dataset_row_ids
            + split_artifact.test.dataset_row_ids
        )
        missing = tuple(sorted(set(split_ids) - set(row_by_id)))
        if missing:
            raise Beta4AGateError(
                "LEAKAGE_ROW_EVIDENCE_MISSING",
                f"missing evidence for split rows: {', '.join(missing)}",
            )

        findings: list[LeakageFinding] = []
        findings.extend(self._temporal_findings(tuple(row_by_id[row_id] for row_id in split_ids)))
        findings.extend(self._structural_group_findings(split_artifact, row_by_id))
        findings.extend(self._cross_bundle_findings(bundle_memberships))
        correlation_findings, checked_features = self._correlation_findings(
            tuple(row_by_id[row_id] for row_id in split_ids),
            suspicious_correlation_threshold,
            minimum_correlation_pairs,
        )
        findings.extend(correlation_findings)
        findings.sort(
            key=lambda item: (
                0 if item.severity is LeakageSeverity.HARD_BLOCK else 1,
                item.code,
                item.feature_name or "",
                item.dataset_row_ids,
            )
        )
        status = (
            LeakageReportStatus.BLOCKED
            if any(item.severity is LeakageSeverity.HARD_BLOCK for item in findings)
            else LeakageReportStatus.PASS
        )
        payload = {
            "split_sha256": split_artifact.split_sha256,
            "bundle_sha256": bundle_sha256,
            "feature_schema_identity": feature_schema_identity,
            "status": status.value,
            "findings": [self._finding_payload(item) for item in findings],
            "checked_row_count": len(split_ids),
            "checked_feature_count": checked_features,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        return LeakageDetectionReport(
            report_id=f"leakage-{digest[:16]}",
            report_sha256=digest,
            split_sha256=split_artifact.split_sha256,
            bundle_sha256=bundle_sha256,
            feature_schema_identity=feature_schema_identity,
            status=status,
            findings=tuple(findings),
            checked_row_count=len(split_ids),
            checked_feature_count=checked_features,
        )

    @staticmethod
    def require_pass(report: LeakageDetectionReport) -> None:
        if report.status is not LeakageReportStatus.PASS:
            codes = ", ".join(sorted({item.code for item in report.hard_blocks}))
            raise Beta4AGateError("LEAKAGE_REPORT_HARD_BLOCKED", codes or "leakage report is blocked")

    @classmethod
    def _temporal_findings(cls, rows: Sequence[LeakageRowEvidence]) -> list[LeakageFinding]:
        findings: list[LeakageFinding] = []
        for row in rows:
            if row.snapshot_timestamp is None or row.first_eligible_evaluation_timestamp is None:
                findings.append(
                    LeakageFinding(
                        "TEMPORAL_LINEAGE_EVIDENCE_MISSING",
                        LeakageSeverity.HARD_BLOCK,
                        "snapshot_timestamp and first_eligible_evaluation_timestamp are required",
                        (row.dataset_row_id,),
                    )
                )
                continue
            snapshot = cls._parse_timestamp(row.snapshot_timestamp, row.dataset_row_id)
            eligible = cls._parse_timestamp(row.first_eligible_evaluation_timestamp, row.dataset_row_id)
            if snapshot > eligible:
                findings.append(
                    LeakageFinding(
                        "TEMPORAL_CONSISTENCY_VIOLATION",
                        LeakageSeverity.HARD_BLOCK,
                        "snapshot_timestamp is after first_eligible_evaluation_timestamp",
                        (row.dataset_row_id,),
                    )
                )
        return findings

    @staticmethod
    def _structural_group_findings(
        split: SplitArtifact,
        row_by_id: Mapping[str, LeakageRowEvidence],
    ) -> list[LeakageFinding]:
        partitions = {
            "train": split.train.dataset_row_ids,
            "validation": split.validation.dataset_row_ids,
            "test": split.test.dataset_row_ids,
        }
        group_to_parts: dict[str, set[str]] = {}
        group_to_ids: dict[str, list[str]] = {}
        for partition, ids in partitions.items():
            for row_id in ids:
                row = row_by_id[row_id]
                group_to_parts.setdefault(row.structural_group_id, set()).add(partition)
                group_to_ids.setdefault(row.structural_group_id, []).append(row_id)
        return [
            LeakageFinding(
                "SHARED_STRUCTURAL_GROUP_SPLIT_VIOLATION",
                LeakageSeverity.HARD_BLOCK,
                f"structural group {group} spans partitions: {', '.join(sorted(parts))}",
                tuple(sorted(group_to_ids[group])),
            )
            for group, parts in sorted(group_to_parts.items())
            if len(parts) > 1
        ]

    @staticmethod
    def _cross_bundle_findings(
        memberships: Sequence[BundleRowMembership | Mapping[str, object]],
    ) -> list[LeakageFinding]:
        bundles_by_row: dict[str, set[str]] = {}
        for raw in memberships:
            membership = LeakageDetector._coerce_membership(raw)
            bundles_by_row.setdefault(membership.dataset_row_id, set()).add(membership.bundle_sha256)
        return [
            LeakageFinding(
                "CROSS_BUNDLE_DUPLICATE_IDENTITY",
                LeakageSeverity.HARD_BLOCK,
                f"dataset row appears in multiple bundles: {', '.join(sorted(bundles))}",
                (row_id,),
            )
            for row_id, bundles in sorted(bundles_by_row.items())
            if len(bundles) > 1
        ]

    @staticmethod
    def _correlation_findings(
        rows: Sequence[LeakageRowEvidence], threshold: float, minimum_pairs: int
    ) -> tuple[list[LeakageFinding], int]:
        feature_names = sorted(
            {
                name
                for row in rows
                for name in ((row.feature_values or {}).keys())
            }
        )
        findings: list[LeakageFinding] = []
        for feature_name in feature_names:
            pairs: list[tuple[float, float]] = []
            for row in rows:
                value = (row.feature_values or {}).get(feature_name)
                if LeakageDetector._is_finite_number(value) and LeakageDetector._is_finite_number(row.label_value):
                    pairs.append((float(value), float(row.label_value)))
            if len(pairs) < minimum_pairs:
                continue
            correlation = LeakageDetector._pearson(pairs)
            if correlation is not None and abs(correlation) >= threshold:
                findings.append(
                    LeakageFinding(
                        "SUSPICIOUS_LABEL_CORRELATION",
                        LeakageSeverity.WARNING,
                        "raw feature/label correlation exceeds descriptive warning threshold",
                        feature_name=feature_name,
                        observed_value=correlation,
                    )
                )
        return findings, len(feature_names)

    @staticmethod
    def _pearson(pairs: Sequence[tuple[float, float]]) -> float | None:
        count = len(pairs)
        mean_x = sum(x for x, _ in pairs) / count
        mean_y = sum(y for _, y in pairs) / count
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
        sum_x = sum((x - mean_x) ** 2 for x, _ in pairs)
        sum_y = sum((y - mean_y) ** 2 for _, y in pairs)
        denominator = math.sqrt(sum_x * sum_y)
        if denominator == 0.0:
            return None
        return max(-1.0, min(1.0, numerator / denominator))

    @staticmethod
    def _is_finite_number(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))

    @staticmethod
    def _parse_timestamp(value: str, row_id: str) -> datetime:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except (AttributeError, ValueError) as exc:
            raise Beta4AGateError(
                "INVALID_LEAKAGE_TIMESTAMP",
                f"invalid timestamp for row {row_id}: {value}",
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _coerce_row(row: LeakageRowEvidence | Mapping[str, object]) -> LeakageRowEvidence:
        if isinstance(row, LeakageRowEvidence):
            return row
        if not isinstance(row, Mapping):
            raise TypeError("rows must contain LeakageRowEvidence or mapping values")
        try:
            feature_values = row.get("feature_values")
            if feature_values is not None and not isinstance(feature_values, Mapping):
                raise Beta4AGateError("LEAKAGE_ROW_SCHEMA_MISMATCH", "feature_values must be a mapping")
            return LeakageRowEvidence(
                dataset_row_id=str(row["dataset_row_id"]),
                structural_group_id=str(row["structural_group_id"]),
                snapshot_timestamp=None if row.get("snapshot_timestamp") is None else str(row["snapshot_timestamp"]),
                first_eligible_evaluation_timestamp=(
                    None
                    if row.get("first_eligible_evaluation_timestamp") is None
                    else str(row["first_eligible_evaluation_timestamp"])
                ),
                label_value=row.get("label_value"),
                feature_values=feature_values,
            )
        except KeyError as exc:
            raise Beta4AGateError("LEAKAGE_ROW_SCHEMA_MISMATCH", f"missing row field: {exc.args[0]}") from exc

    @staticmethod
    def _coerce_membership(
        value: BundleRowMembership | Mapping[str, object]
    ) -> BundleRowMembership:
        if isinstance(value, BundleRowMembership):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("bundle_memberships must contain BundleRowMembership or mappings")
        try:
            return BundleRowMembership(str(value["dataset_row_id"]), str(value["bundle_sha256"]))
        except KeyError as exc:
            raise Beta4AGateError("BUNDLE_MEMBERSHIP_SCHEMA_MISMATCH", f"missing field: {exc.args[0]}") from exc

    @staticmethod
    def _verify_unique_rows(rows: Sequence[LeakageRowEvidence]) -> None:
        ids = [row.dataset_row_id for row in rows]
        if len(ids) != len(set(ids)):
            raise Beta4AGateError("DUPLICATE_DATASET_ROW_ID", "leakage evidence row ids must be unique")

    @staticmethod
    def _finding_payload(finding: LeakageFinding) -> dict[str, object]:
        return {
            "code": finding.code,
            "severity": finding.severity.value,
            "message": finding.message,
            "dataset_row_ids": finding.dataset_row_ids,
            "feature_name": finding.feature_name,
            "observed_value": finding.observed_value,
        }
