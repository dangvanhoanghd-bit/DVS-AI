from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .contracts import FeatureColumn, FeatureSchemaIdentity, FeatureSchemaManifest
from .dataset_split import SplitArtifact
from .errors import Beta4AGateError
from .leakage_detector import LeakageDetectionReport, LeakageDetector


class MissingFeaturePolicy(str, Enum):
    HARD_BLOCK = "HARD_BLOCK"
    EXCLUDE_ROW = "EXCLUDE_ROW"


@dataclass(frozen=True, slots=True)
class FeatureMatrixSourceRow:
    dataset_row_id: str
    feature_values: Mapping[str, Any]
    label_value: float | int | None = None

    def __post_init__(self) -> None:
        if not self.dataset_row_id:
            raise ValueError("dataset_row_id must be non-empty")
        if not isinstance(self.feature_values, Mapping):
            raise TypeError("feature_values must be a mapping")


@dataclass(frozen=True, slots=True)
class FeatureMatrixExclusion:
    dataset_row_id: str
    code: str
    feature_name: str
    message: str


@dataclass(frozen=True, slots=True)
class FeatureMatrixPartition:
    name: str
    dataset_row_ids: tuple[str, ...]
    values: tuple[tuple[float | int, ...], ...]
    labels: tuple[float | int | None, ...]


@dataclass(frozen=True, slots=True)
class TrainingFeatureMatrixArtifact:
    """Trainer-safe matrix view. It intentionally has no Test partition."""

    matrix_id: str
    matrix_sha256: str
    split_sha256: str
    bundle_sha256: str
    leakage_report_sha256: str
    feature_schema_identity: FeatureSchemaIdentity
    ordered_feature_names: tuple[str, ...]
    train: FeatureMatrixPartition
    validation: FeatureMatrixPartition
    exclusions: tuple[FeatureMatrixExclusion, ...]


@dataclass(frozen=True, slots=True)
class FeatureMatrixArtifact:
    matrix_id: str
    matrix_sha256: str
    split_sha256: str
    bundle_sha256: str
    leakage_report_sha256: str
    feature_schema_identity: FeatureSchemaIdentity
    ordered_feature_names: tuple[str, ...]
    train: FeatureMatrixPartition
    validation: FeatureMatrixPartition
    test: FeatureMatrixPartition
    exclusions: tuple[FeatureMatrixExclusion, ...]

    @property
    def included_row_count(self) -> int:
        return len(self.train.dataset_row_ids) + len(self.validation.dataset_row_ids) + len(self.test.dataset_row_ids)

    def training_view(self) -> TrainingFeatureMatrixArtifact:
        """Return the only artifact permitted to cross the trainer boundary."""
        return TrainingFeatureMatrixArtifact(
            matrix_id=self.matrix_id,
            matrix_sha256=self.matrix_sha256,
            split_sha256=self.split_sha256,
            bundle_sha256=self.bundle_sha256,
            leakage_report_sha256=self.leakage_report_sha256,
            feature_schema_identity=self.feature_schema_identity,
            ordered_feature_names=self.ordered_feature_names,
            train=self.train,
            validation=self.validation,
            exclusions=self.exclusions,
        )


class FeatureMatrixBuilder:
    """Deterministic Beta 4A M2 matrix builder.

    The builder consumes the frozen schema and already-produced split/leakage
    artifacts. It never fits encoders, invents columns, imputes values, or
    recomputes lower-layer metrics.
    """

    def build(
        self,
        rows: Iterable[FeatureMatrixSourceRow | Mapping[str, object]],
        *,
        schema: FeatureSchemaManifest,
        split_artifact: SplitArtifact,
        leakage_report: LeakageDetectionReport,
        bundle_sha256: str,
        missing_feature_policy: MissingFeaturePolicy = MissingFeaturePolicy.EXCLUDE_ROW,
        expected_column_order: Sequence[str] | None = None,
        include_test: bool = True,
    ) -> FeatureMatrixArtifact:
        LeakageDetector.require_pass(leakage_report)
        self._verify_artifact_links(schema, split_artifact, leakage_report, bundle_sha256)
        if expected_column_order is not None and tuple(expected_column_order) != schema.ordered_names():
            raise Beta4AGateError("COLUMN_ORDER_MISMATCH", "requested column order differs from frozen feature schema")

        normalized = tuple(self._coerce_row(row) for row in rows)
        row_by_id: dict[str, FeatureMatrixSourceRow] = {}
        for row in normalized:
            if row.dataset_row_id in row_by_id:
                raise Beta4AGateError("FEATURE_SCHEMA_MISMATCH", f"duplicate dataset_row_id: {row.dataset_row_id}")
            row_by_id[row.dataset_row_id] = row

        partitions: dict[str, FeatureMatrixPartition] = {}
        exclusions: list[FeatureMatrixExclusion] = []
        partition_specs = [
            ("train", split_artifact.train.dataset_row_ids),
            ("validation", split_artifact.validation.dataset_row_ids),
        ]
        partition_specs.append(("test", split_artifact.test.dataset_row_ids if include_test else ()))
        for name, ids in partition_specs:
            built_ids: list[str] = []
            built_values: list[tuple[float | int, ...]] = []
            built_labels: list[float | int | None] = []
            for row_id in ids:
                source = row_by_id.get(row_id)
                if source is None:
                    if missing_feature_policy is MissingFeaturePolicy.HARD_BLOCK:
                        raise Beta4AGateError("FEATURE_SCHEMA_MISMATCH", f"missing source row: {row_id}")
                    exclusions.append(FeatureMatrixExclusion(row_id, "ROW_EXCLUDED_INCOMPLETE_SCHEMA", "*", "source row is missing"))
                    continue
                encoded, exclusion = self._encode_row(source, schema)
                if exclusion is not None:
                    if exclusion.code == "ROW_EXCLUDED_INCOMPLETE_SCHEMA" and missing_feature_policy is MissingFeaturePolicy.HARD_BLOCK:
                        raise Beta4AGateError("FEATURE_SCHEMA_MISMATCH", exclusion.message)
                    exclusions.append(exclusion)
                    continue
                built_ids.append(row_id)
                built_values.append(encoded)
                built_labels.append(source.label_value)
            partitions[name] = FeatureMatrixPartition(name, tuple(built_ids), tuple(built_values), tuple(built_labels))

        payload = {
            "split_sha256": split_artifact.split_sha256,
            "bundle_sha256": bundle_sha256,
            "leakage_report_sha256": leakage_report.report_sha256,
            "feature_schema_identity": asdict(schema.identity),
            "ordered_feature_names": list(schema.ordered_names()),
            "partitions": {
                name: {
                    "dataset_row_ids": list(part.dataset_row_ids),
                    "values": [list(row) for row in part.values],
                    "labels": list(part.labels),
                }
                for name, part in partitions.items()
            },
            "exclusions": [asdict(item) for item in sorted(exclusions, key=lambda x: (x.dataset_row_id, x.code, x.feature_name))],
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        return FeatureMatrixArtifact(
            matrix_id=f"matrix-{digest[:16]}",
            matrix_sha256=digest,
            split_sha256=split_artifact.split_sha256,
            bundle_sha256=bundle_sha256,
            leakage_report_sha256=leakage_report.report_sha256,
            feature_schema_identity=schema.identity,
            ordered_feature_names=schema.ordered_names(),
            train=partitions["train"],
            validation=partitions["validation"],
            test=partitions["test"],
            exclusions=tuple(sorted(exclusions, key=lambda x: (x.dataset_row_id, x.code, x.feature_name))),
        )

    @staticmethod
    def write_schema_manifest(schema: FeatureSchemaManifest, path: str | Path) -> str:
        payload = {
            "feature_schema_version": schema.feature_schema_version,
            "feature_schema_identity": asdict(schema.identity),
            "columns": [asdict(column) for column in schema.columns],
        }
        text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _verify_artifact_links(
        schema: FeatureSchemaManifest,
        split: SplitArtifact,
        report: LeakageDetectionReport,
        bundle_sha256: str,
    ) -> None:
        if split.source_bundle_sha256 != bundle_sha256 or report.bundle_sha256 != bundle_sha256:
            raise Beta4AGateError("FEATURE_SCHEMA_MISMATCH", "bundle identity mismatch across M2 inputs")
        if report.split_sha256 != split.split_sha256:
            raise Beta4AGateError("FEATURE_SCHEMA_MISMATCH", "split identity mismatch across M2 inputs")
        expected = schema.identity.ordered_feature_list_hash
        if report.feature_schema_identity is not None and report.feature_schema_identity != expected:
            raise Beta4AGateError("FEATURE_SCHEMA_MISMATCH", "leakage report feature schema identity mismatch")

    @staticmethod
    def _encode_row(
        row: FeatureMatrixSourceRow,
        schema: FeatureSchemaManifest,
    ) -> tuple[tuple[float | int, ...], FeatureMatrixExclusion | None]:
        values: list[float | int] = []
        for column in schema.columns:
            if column.name not in row.feature_values or row.feature_values[column.name] is None:
                return (), FeatureMatrixExclusion(
                    row.dataset_row_id,
                    "ROW_EXCLUDED_INCOMPLETE_SCHEMA",
                    column.name,
                    f"required feature is missing: {column.name}",
                )
            raw = row.feature_values[column.name]
            try:
                values.append(FeatureMatrixBuilder._encode_value(raw, column))
            except Beta4AGateError as exc:
                return (), FeatureMatrixExclusion(row.dataset_row_id, exc.code, column.name, exc.message)
        return tuple(values), None

    @staticmethod
    def _encode_value(value: object, column: FeatureColumn) -> float | int:
        if column.encoding in {"identity", "numeric"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise Beta4AGateError("FEATURE_SCHEMA_MISMATCH", f"non-finite numeric value for {column.name}")
            if column.dtype.startswith("int"):
                if isinstance(value, float) and not value.is_integer():
                    raise Beta4AGateError("FEATURE_SCHEMA_MISMATCH", f"non-integral value for {column.name}")
                return int(value)
            return float(value)
        if column.encoding == "boolean":
            if not isinstance(value, bool):
                raise Beta4AGateError("FEATURE_SCHEMA_MISMATCH", f"non-boolean value for {column.name}")
            return 1 if value else 0
        if column.encoding == "categorical":
            text = str(value)
            try:
                return column.categories.index(text)
            except ValueError as exc:
                raise Beta4AGateError("UNSEEN_CATEGORICAL_VALUE", f"unseen category for {column.name}: {text}") from exc
        raise Beta4AGateError("FEATURE_SCHEMA_MISMATCH", f"unsupported encoding for {column.name}: {column.encoding}")

    @staticmethod
    def _coerce_row(row: FeatureMatrixSourceRow | Mapping[str, object]) -> FeatureMatrixSourceRow:
        if isinstance(row, FeatureMatrixSourceRow):
            return row
        if not isinstance(row, Mapping):
            raise TypeError("rows must contain FeatureMatrixSourceRow or mapping values")
        try:
            features = row["feature_values"]
            if not isinstance(features, Mapping):
                raise Beta4AGateError("FEATURE_SCHEMA_MISMATCH", "feature_values must be a mapping")
            return FeatureMatrixSourceRow(str(row["dataset_row_id"]), features, row.get("label_value"))
        except KeyError as exc:
            raise Beta4AGateError("FEATURE_SCHEMA_MISMATCH", f"missing row field: {exc.args[0]}") from exc


__all__ = [
    "FeatureColumn",
    "FeatureMatrixArtifact",
    "FeatureMatrixBuilder",
    "FeatureMatrixExclusion",
    "FeatureMatrixPartition",
    "FeatureMatrixSourceRow",
    "FeatureSchemaIdentity",
    "FeatureSchemaManifest",
    "MissingFeaturePolicy",
]
