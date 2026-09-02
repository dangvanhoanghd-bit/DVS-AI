from __future__ import annotations

from dataclasses import replace
import json

import pytest

from dvs_ai.beta4a.contracts import FeatureColumn, FeatureSchemaManifest
from dvs_ai.beta4a.dataset_split import DatasetRowRecord, DatasetSplitEngine
from dvs_ai.beta4a.errors import Beta4AGateError
from dvs_ai.beta4a.feature_schema import (
    FeatureMatrixBuilder,
    FeatureMatrixSourceRow,
    MissingFeaturePolicy,
)
from dvs_ai.beta4a.leakage_detector import LeakageDetector, LeakageRowEvidence


def _schema() -> FeatureSchemaManifest:
    return FeatureSchemaManifest(
        "beta4a-m2-v1",
        (
            FeatureColumn("rsi", "float64", "numeric", 0),
            FeatureColumn("trend", "category", "categorical", 1, ("DOWN", "FLAT", "UP")),
            FeatureColumn("confirmed", "bool", "boolean", 2),
        ),
    )


def _split():
    rows = [
        DatasetRowRecord(
            f"r{i:02d}",
            f"2026-01-{i + 1:02d}T10:00:00Z",
            f"2026-01-{i + 1:02d}T12:00:00Z",
            f"g{i:02d}",
        )
        for i in range(12)
    ]
    return DatasetSplitEngine().split(rows, source_bundle_sha256="bundle-a")


def _source_rows(split):
    ids = split.train.dataset_row_ids + split.validation.dataset_row_ids + split.test.dataset_row_ids
    return [
        FeatureMatrixSourceRow(
            row_id,
            {
                "confirmed": index % 2 == 0,
                "trend": ("DOWN", "FLAT", "UP")[index % 3],
                "rsi": 40.0 + index,
                "ignored_extra": "not-a-column",
            },
            label_value=index % 2,
        )
        for index, row_id in enumerate(ids)
    ]


def _leakage_report(split, schema):
    ids = split.train.dataset_row_ids + split.validation.dataset_row_ids + split.test.dataset_row_ids
    evidence = [
        LeakageRowEvidence(
            row_id,
            f"g{int(row_id[1:]):02d}",
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
            label_value=index % 2,
            feature_values={"rsi": (index * 7) % 5},
        )
        for index, row_id in enumerate(ids)
    ]
    return LeakageDetector().detect(
        evidence,
        split_artifact=split,
        bundle_sha256="bundle-a",
        feature_schema_identity=schema.identity.ordered_feature_list_hash,
    )


def test_feature_schema_identity_includes_frozen_categories():
    original = _schema()
    changed = FeatureSchemaManifest(
        original.feature_schema_version,
        (
            original.columns[0],
            replace(original.columns[1], categories=("UP", "FLAT", "DOWN")),
            original.columns[2],
        ),
    )
    assert original.identity != changed.identity


def test_build_is_deterministic_and_uses_schema_column_order():
    split = _split()
    schema = _schema()
    report = _leakage_report(split, schema)
    rows = _source_rows(split)
    builder = FeatureMatrixBuilder()
    first = builder.build(rows, schema=schema, split_artifact=split, leakage_report=report, bundle_sha256="bundle-a")
    repeated = builder.build(reversed(rows), schema=schema, split_artifact=split, leakage_report=report, bundle_sha256="bundle-a")
    assert first == repeated
    assert first.ordered_feature_names == ("rsi", "trend", "confirmed")
    assert first.train.values[0] == (40.0, 0, 1)
    assert len(first.matrix_sha256) == 64


def test_missing_feature_is_excluded_without_imputation_by_default():
    split = _split()
    schema = _schema()
    report = _leakage_report(split, schema)
    rows = _source_rows(split)
    target = split.train.dataset_row_ids[0]
    rows = [
        replace(row, feature_values={k: v for k, v in row.feature_values.items() if k != "rsi"})
        if row.dataset_row_id == target else row
        for row in rows
    ]
    artifact = FeatureMatrixBuilder().build(
        rows, schema=schema, split_artifact=split, leakage_report=report, bundle_sha256="bundle-a"
    )
    assert target not in artifact.train.dataset_row_ids
    exclusion = next(item for item in artifact.exclusions if item.dataset_row_id == target)
    assert exclusion.code == "ROW_EXCLUDED_INCOMPLETE_SCHEMA"


def test_missing_feature_can_be_hard_blocked_explicitly():
    split = _split()
    schema = _schema()
    report = _leakage_report(split, schema)
    rows = _source_rows(split)
    rows[0] = replace(rows[0], feature_values={"trend": "UP", "confirmed": True})
    with pytest.raises(Beta4AGateError) as exc:
        FeatureMatrixBuilder().build(
            rows,
            schema=schema,
            split_artifact=split,
            leakage_report=report,
            bundle_sha256="bundle-a",
            missing_feature_policy=MissingFeaturePolicy.HARD_BLOCK,
        )
    assert exc.value.code == "FEATURE_SCHEMA_MISMATCH"


def test_unseen_category_excludes_row_and_never_creates_column():
    split = _split()
    schema = _schema()
    report = _leakage_report(split, schema)
    rows = _source_rows(split)
    target = split.validation.dataset_row_ids[0]
    rows = [replace(row, feature_values={**row.feature_values, "trend": "SIDEWAYS"}) if row.dataset_row_id == target else row for row in rows]
    artifact = FeatureMatrixBuilder().build(rows, schema=schema, split_artifact=split, leakage_report=report, bundle_sha256="bundle-a")
    assert target not in artifact.validation.dataset_row_ids
    exclusion = next(item for item in artifact.exclusions if item.dataset_row_id == target)
    assert exclusion.code == "UNSEEN_CATEGORICAL_VALUE"
    assert artifact.ordered_feature_names == schema.ordered_names()


def test_column_order_mismatch_is_hard_block():
    split = _split()
    schema = _schema()
    report = _leakage_report(split, schema)
    with pytest.raises(Beta4AGateError) as exc:
        FeatureMatrixBuilder().build(
            _source_rows(split),
            schema=schema,
            split_artifact=split,
            leakage_report=report,
            bundle_sha256="bundle-a",
            expected_column_order=("trend", "rsi", "confirmed"),
        )
    assert exc.value.code == "COLUMN_ORDER_MISMATCH"


def test_schema_identity_mismatch_with_leakage_report_is_hard_block():
    split = _split()
    schema = _schema()
    report = replace(_leakage_report(split, schema), feature_schema_identity="wrong")
    with pytest.raises(Beta4AGateError) as exc:
        FeatureMatrixBuilder().build(_source_rows(split), schema=schema, split_artifact=split, leakage_report=report, bundle_sha256="bundle-a")
    assert exc.value.code == "FEATURE_SCHEMA_MISMATCH"


def test_blocked_leakage_report_cannot_enter_m2():
    split = _split()
    schema = _schema()
    report = _leakage_report(split, schema)
    blocked_evidence = [
        LeakageRowEvidence(
            row_id,
            f"g{int(row_id[1:]):02d}",
            None if index == 0 else "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
        )
        for index, row_id in enumerate(split.train.dataset_row_ids + split.validation.dataset_row_ids + split.test.dataset_row_ids)
    ]
    blocked = LeakageDetector().detect(
        blocked_evidence,
        split_artifact=split,
        bundle_sha256="bundle-a",
        feature_schema_identity=schema.identity.ordered_feature_list_hash,
    )
    with pytest.raises(Beta4AGateError) as exc:
        FeatureMatrixBuilder().build(_source_rows(split), schema=schema, split_artifact=split, leakage_report=blocked, bundle_sha256="bundle-a")
    assert exc.value.code == "LEAKAGE_REPORT_HARD_BLOCKED"
    assert report.status.value == "PASS"


def test_schema_manifest_is_stable_and_machine_readable(tmp_path):
    schema = _schema()
    path = tmp_path / "feature_schema.manifest.json"
    first_hash = FeatureMatrixBuilder.write_schema_manifest(schema, path)
    first_text = path.read_text(encoding="utf-8")
    second_hash = FeatureMatrixBuilder.write_schema_manifest(schema, path)
    assert first_hash == second_hash
    payload = json.loads(first_text)
    assert payload["feature_schema_identity"]["ordered_feature_list_hash"] == schema.identity.ordered_feature_list_hash
    assert [column["name"] for column in payload["columns"]] == list(schema.ordered_names())
