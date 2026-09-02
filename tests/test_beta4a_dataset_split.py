from __future__ import annotations

from dataclasses import replace

import pytest

from dvs_ai.beta4a.contracts import HoldoutConsumptionRecord, TestStatus as HoldoutTestStatus
from dvs_ai.beta4a.dataset_split import DatasetRowRecord, DatasetSplitEngine, SplitConfig
from dvs_ai.beta4a.errors import Beta4AGateError
from dvs_ai.beta4a.locked_test_registry import LockedTestRegistryEntry, LockedTestRowRegistry


def row(index: int, *, setup_offset: int | None = None, group: str | None = None) -> DatasetRowRecord:
    day = index + 1
    setup_day = setup_offset if setup_offset is not None else day
    return DatasetRowRecord(
        dataset_row_id=f"r{index:02d}",
        setup_time=f"2026-01-{setup_day:02d}T12:00:00Z",
        close_time=f"2026-01-{day:02d}T12:00:00Z",
        structural_group_id=group or f"g{index:02d}",
    )


def test_walk_forward_split_is_temporal_deterministic_and_locks_test():
    rows = [row(i) for i in range(12)]
    engine = DatasetSplitEngine()
    first = engine.split(rows, source_bundle_sha256="bundle-a")
    repeated = engine.split(reversed(rows), source_bundle_sha256="bundle-a")
    assert first == repeated
    assert first.test_status is HoldoutTestStatus.LOCKED_UNCONSUMED
    assert first.train.dataset_row_ids == tuple(f"r{i:02d}" for i in range(7))
    assert first.validation.dataset_row_ids == ("r07", "r08")
    assert first.test.dataset_row_ids == ("r09", "r10", "r11")


def test_boundary_overlapping_candidate_is_purged():
    rows = [row(i) for i in range(10)]
    # r05 closes before the train boundary but starts before and closes at it after replacement.
    rows[6] = DatasetRowRecord("r06", "2026-01-01T00:00:00Z", "2026-01-07T12:00:00Z", "g06")
    artifact = DatasetSplitEngine().split(rows, source_bundle_sha256="bundle-a")
    assert "r06" not in artifact.train.dataset_row_ids + artifact.validation.dataset_row_ids + artifact.test.dataset_row_ids
    assert artifact.purge_count >= 1


def test_embargo_is_counted_separately_from_purge():
    rows = [row(i) for i in range(15)]
    artifact = DatasetSplitEngine().split(
        rows,
        source_bundle_sha256="bundle-a",
        config=SplitConfig(embargo_seconds=60 * 60 * 24 * 2),
    )
    assert artifact.embargo_count > 0
    assert artifact.purge_count == 0


def test_structural_group_is_never_split_across_partitions():
    rows = [row(i) for i in range(12)]
    rows[6] = replace(rows[6], structural_group_id="shared")
    rows[8] = replace(rows[8], structural_group_id="shared")
    artifact = DatasetSplitEngine().split(rows, source_bundle_sha256="bundle-a")
    all_ids = artifact.train.dataset_row_ids + artifact.validation.dataset_row_ids + artifact.test.dataset_row_ids
    assert "r06" not in all_ids and "r08" not in all_ids
    assert artifact.structural_group_exclusion_count == 2


def test_prior_locked_and_consumed_rows_are_excluded_and_reported():
    rows = [row(i) for i in range(14)]
    registry = (
        LockedTestRegistryEntry("r01", HoldoutTestStatus.LOCKED_UNCONSUMED, "old-a"),
        LockedTestRegistryEntry("r02", HoldoutTestStatus.CONSUMED, "old-b"),
    )
    artifact = DatasetSplitEngine().split(rows, source_bundle_sha256="bundle-a", locked_test_registry=registry)
    all_ids = artifact.train.dataset_row_ids + artifact.validation.dataset_row_ids + artifact.test.dataset_row_ids
    assert "r01" not in all_ids and "r02" not in all_ids
    assert artifact.prior_locked_exclusion_count == 1
    assert artifact.prior_consumed_exclusion_count == 1


def test_each_partition_has_independent_sample_floor():
    rows = [row(i) for i in range(12)]
    with pytest.raises(Beta4AGateError) as exc:
        DatasetSplitEngine().split(
            rows,
            source_bundle_sha256="bundle-a",
            config=SplitConfig(min_validation_rows=4),
        )
    assert exc.value.code == "SPLIT_SAMPLE_FLOOR_NOT_MET"


def test_registry_rebuild_marks_consumed_and_rejects_duplicate_test_history():
    rows = [row(i) for i in range(12)]
    split = DatasetSplitEngine().split(rows, source_bundle_sha256="bundle-a")
    consumption = HoldoutConsumptionRecord(split.split_sha256, "m1", "2026-02-01T00:00:00Z", "qualifying", "report-a")
    registry = LockedTestRowRegistry().rebuild([split], [consumption])
    assert registry and all(entry.status is HoldoutTestStatus.CONSUMED for entry in registry)

    other = replace(split, split_id="other", split_sha256="f" * 64)
    with pytest.raises(Beta4AGateError) as exc:
        LockedTestRowRegistry().rebuild([split, other], [])
    assert exc.value.code == "LOCK_HISTORY_CONFLICT"


def test_registry_rebuild_detects_test_to_train_cross_split_conflict():
    rows = [row(i) for i in range(18)]
    first = DatasetSplitEngine().split(rows[:12], source_bundle_sha256="bundle-a")
    second = DatasetSplitEngine().split(rows[6:18], source_bundle_sha256="bundle-b")
    # Force a previously locked Test row into TRAIN of another immutable split.
    from dataclasses import replace
    conflict_row = first.test.dataset_row_ids[0]
    second = replace(second, train=replace(second.train, dataset_row_ids=(conflict_row,) + second.train.dataset_row_ids))
    with pytest.raises(Beta4AGateError) as exc:
        LockedTestRowRegistry().rebuild([first, second], [])
    assert exc.value.code == "LOCK_HISTORY_CONFLICT"
