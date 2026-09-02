from __future__ import annotations

from dataclasses import replace

import pytest

from dvs_ai.beta4a.dataset_split import DatasetRowRecord, DatasetSplitEngine
from dvs_ai.beta4a.errors import Beta4AGateError
from dvs_ai.beta4a.leakage_detector import (
    BundleRowMembership,
    LeakageDetector,
    LeakageReportStatus,
    LeakageRowEvidence,
    LeakageSeverity,
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


def _evidence(split):
    ids = split.train.dataset_row_ids + split.validation.dataset_row_ids + split.test.dataset_row_ids
    return [
        LeakageRowEvidence(
            row_id,
            f"g{int(row_id[1:]):02d}",
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
            label_value=index % 2,
            feature_values={"feature_a": (index * 7) % 5},
        )
        for index, row_id in enumerate(ids)
    ]


def test_clean_evidence_produces_deterministic_pass_report():
    split = _split()
    detector = LeakageDetector()
    rows = _evidence(split)
    first = detector.detect(rows, split_artifact=split, bundle_sha256="bundle-a", feature_schema_identity="schema-a")
    repeated = detector.detect(reversed(rows), split_artifact=split, bundle_sha256="bundle-a", feature_schema_identity="schema-a")
    assert first == repeated
    assert first.status is LeakageReportStatus.PASS
    assert not first.hard_blocks
    assert len(first.report_sha256) == 64


def test_temporal_consistency_violation_is_hard_block():
    split = _split()
    rows = _evidence(split)
    rows[0] = replace(
        rows[0],
        snapshot_timestamp="2026-01-03T00:00:00Z",
        first_eligible_evaluation_timestamp="2026-01-02T00:00:00Z",
    )
    report = LeakageDetector().detect(rows, split_artifact=split, bundle_sha256="bundle-a")
    assert report.status is LeakageReportStatus.BLOCKED
    assert any(item.code == "TEMPORAL_CONSISTENCY_VIOLATION" for item in report.hard_blocks)


def test_missing_temporal_lineage_is_fail_closed():
    split = _split()
    rows = _evidence(split)
    rows[0] = replace(rows[0], snapshot_timestamp=None)
    report = LeakageDetector().detect(rows, split_artifact=split, bundle_sha256="bundle-a")
    assert any(item.code == "TEMPORAL_LINEAGE_EVIDENCE_MISSING" for item in report.hard_blocks)


def test_shared_structural_group_across_partitions_is_hard_block():
    split = _split()
    rows = _evidence(split)
    train_id = split.train.dataset_row_ids[0]
    test_id = split.test.dataset_row_ids[0]
    rows = [
        replace(row, structural_group_id="shared") if row.dataset_row_id in {train_id, test_id} else row
        for row in rows
    ]
    report = LeakageDetector().detect(rows, split_artifact=split, bundle_sha256="bundle-a")
    finding = next(item for item in report.hard_blocks if item.code == "SHARED_STRUCTURAL_GROUP_SPLIT_VIOLATION")
    assert set(finding.dataset_row_ids) == {train_id, test_id}


def test_cross_bundle_duplicate_identity_is_defense_in_depth_hard_block():
    split = _split()
    memberships = [
        BundleRowMembership("r01", "bundle-a"),
        BundleRowMembership("r01", "bundle-b"),
    ]
    report = LeakageDetector().detect(
        _evidence(split),
        split_artifact=split,
        bundle_sha256="bundle-a",
        bundle_memberships=memberships,
    )
    assert any(item.code == "CROSS_BUNDLE_DUPLICATE_IDENTITY" for item in report.hard_blocks)


def test_suspicious_label_correlation_is_warning_only():
    split = _split()
    rows = _evidence(split)
    rows = [
        replace(row, label_value=index, feature_values={"leaky": index})
        for index, row in enumerate(rows)
    ]
    report = LeakageDetector().detect(rows, split_artifact=split, bundle_sha256="bundle-a")
    assert report.status is LeakageReportStatus.PASS
    warning = next(item for item in report.warnings if item.code == "SUSPICIOUS_LABEL_CORRELATION")
    assert warning.severity is LeakageSeverity.WARNING
    assert warning.feature_name == "leaky"
    assert warning.observed_value == pytest.approx(1.0)


def test_require_pass_blocks_only_hard_blocked_report():
    split = _split()
    rows = _evidence(split)
    clean = LeakageDetector().detect(rows, split_artifact=split, bundle_sha256="bundle-a")
    LeakageDetector.require_pass(clean)
    rows[0] = replace(rows[0], snapshot_timestamp=None)
    blocked = LeakageDetector().detect(rows, split_artifact=split, bundle_sha256="bundle-a")
    with pytest.raises(Beta4AGateError) as exc:
        LeakageDetector.require_pass(blocked)
    assert exc.value.code == "LEAKAGE_REPORT_HARD_BLOCKED"
