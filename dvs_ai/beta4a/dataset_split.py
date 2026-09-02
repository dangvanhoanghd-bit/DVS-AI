from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Iterable, Mapping, Sequence

from .contracts import TestStatus
from .errors import Beta4AGateError
from .locked_test_registry import LockedTestRegistryEntry


def _parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise Beta4AGateError("INVALID_SPLIT_TIMESTAMP", "split timestamps must be non-empty ISO-8601 strings")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise Beta4AGateError("INVALID_SPLIT_TIMESTAMP", f"invalid ISO-8601 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class DatasetRowRecord:
    dataset_row_id: str
    setup_time: str
    close_time: str
    structural_group_id: str

    def __post_init__(self) -> None:
        if not self.dataset_row_id:
            raise ValueError("dataset_row_id must be non-empty")
        if not self.structural_group_id:
            raise ValueError("structural_group_id must be non-empty")
        setup = _parse_timestamp(self.setup_time)
        close = _parse_timestamp(self.close_time)
        if setup > close:
            raise Beta4AGateError(
                "INVALID_CANDIDATE_INTERVAL",
                f"setup_time is after close_time for row {self.dataset_row_id}",
            )


@dataclass(frozen=True, slots=True)
class SplitConfig:
    train_fraction: float = 0.60
    validation_fraction: float = 0.20
    test_fraction: float = 0.20
    embargo_seconds: int = 0
    min_train_rows: int = 1
    min_validation_rows: int = 1
    min_test_rows: int = 1

    def __post_init__(self) -> None:
        fractions = (self.train_fraction, self.validation_fraction, self.test_fraction)
        if any(value <= 0 for value in fractions) or abs(sum(fractions) - 1.0) > 1e-9:
            raise ValueError("split fractions must be positive and sum to 1.0")
        if self.embargo_seconds < 0:
            raise ValueError("embargo_seconds must be non-negative")
        if min(self.min_train_rows, self.min_validation_rows, self.min_test_rows) < 1:
            raise ValueError("partition sample floors must be at least one")


@dataclass(frozen=True, slots=True)
class SplitPartition:
    name: str
    dataset_row_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SplitArtifact:
    split_id: str
    split_sha256: str
    source_bundle_sha256: str
    train: SplitPartition
    validation: SplitPartition
    test: SplitPartition
    test_status: TestStatus
    purge_count: int
    embargo_count: int
    structural_group_exclusion_count: int
    prior_locked_exclusion_count: int
    prior_consumed_exclusion_count: int
    source_record_count: int
    eligible_split_pool_count: int
    train_boundary_timestamp: str
    test_boundary_timestamp: str


class DatasetSplitEngine:
    """Deterministic temporal walk-forward split with purge, embargo and holdout locks.

    The engine only consumes already-produced row timestamps and identities. It does
    not recompute lower-layer quality, coverage, burn-in or lineage metrics.
    """

    def split(
        self,
        rows: Iterable[DatasetRowRecord | Mapping[str, object]],
        *,
        source_bundle_sha256: str,
        config: SplitConfig | None = None,
        locked_test_registry: Sequence[LockedTestRegistryEntry] = (),
    ) -> SplitArtifact:
        cfg = config or SplitConfig()
        normalized = tuple(self._coerce_row(row) for row in rows)
        if not source_bundle_sha256:
            raise ValueError("source_bundle_sha256 must be non-empty")
        self._verify_unique_ids(normalized)

        lock_by_row = {entry.dataset_row_id: entry for entry in locked_test_registry}
        prior_locked = sum(
            1 for row in normalized
            if (entry := lock_by_row.get(row.dataset_row_id)) is not None
            and entry.status is TestStatus.LOCKED_UNCONSUMED
        )
        prior_consumed = sum(
            1 for row in normalized
            if (entry := lock_by_row.get(row.dataset_row_id)) is not None
            and entry.status is TestStatus.CONSUMED
        )
        eligible = tuple(row for row in normalized if row.dataset_row_id not in lock_by_row)
        ordered = tuple(sorted(eligible, key=lambda row: (_parse_timestamp(row.close_time), row.dataset_row_id)))

        if len(ordered) < 3:
            raise Beta4AGateError("SPLIT_SAMPLE_FLOOR_NOT_MET", "fewer than three eligible rows remain")

        train_index = max(1, int(len(ordered) * cfg.train_fraction))
        validation_index = max(train_index + 1, int(len(ordered) * (cfg.train_fraction + cfg.validation_fraction)))
        validation_index = min(validation_index, len(ordered) - 1)
        train_boundary = _parse_timestamp(ordered[train_index].close_time)
        test_boundary = _parse_timestamp(ordered[validation_index].close_time)
        embargo = timedelta(seconds=cfg.embargo_seconds)

        provisional: dict[str, str | None] = {}
        purge_count = 0
        embargo_count = 0
        for row in ordered:
            setup = _parse_timestamp(row.setup_time)
            close = _parse_timestamp(row.close_time)
            partition: str | None
            # Candidate intervals crossing either temporal boundary are purged.
            if setup < train_boundary <= close or setup < test_boundary <= close:
                partition = None
                purge_count += 1
            elif close < train_boundary:
                partition = "train"
            elif close < train_boundary + embargo:
                partition = None
                embargo_count += 1
            elif close < test_boundary:
                partition = "validation"
            elif close < test_boundary + embargo:
                partition = None
                embargo_count += 1
            else:
                partition = "test"
            provisional[row.dataset_row_id] = partition

        # Structural groups are immutable and may not span partitions. Conservatively
        # exclude every row in a group that would otherwise cross a split boundary.
        group_partitions: dict[str, set[str]] = {}
        rows_by_group: dict[str, list[DatasetRowRecord]] = {}
        for row in ordered:
            rows_by_group.setdefault(row.structural_group_id, []).append(row)
            partition = provisional[row.dataset_row_id]
            if partition is not None:
                group_partitions.setdefault(row.structural_group_id, set()).add(partition)
        crossing_groups = {group for group, parts in group_partitions.items() if len(parts) > 1}
        structural_excluded = 0
        for group in crossing_groups:
            for row in rows_by_group[group]:
                if provisional[row.dataset_row_id] is not None:
                    provisional[row.dataset_row_id] = None
                    structural_excluded += 1

        partition_ids = {
            name: tuple(row.dataset_row_id for row in ordered if provisional[row.dataset_row_id] == name)
            for name in ("train", "validation", "test")
        }
        floors = {
            "train": cfg.min_train_rows,
            "validation": cfg.min_validation_rows,
            "test": cfg.min_test_rows,
        }
        failures = {name: (len(partition_ids[name]), floor) for name, floor in floors.items() if len(partition_ids[name]) < floor}
        if failures:
            detail = ", ".join(f"{name}={actual}<{floor}" for name, (actual, floor) in failures.items())
            raise Beta4AGateError("SPLIT_SAMPLE_FLOOR_NOT_MET", detail)

        payload = {
            "source_bundle_sha256": source_bundle_sha256,
            "train": partition_ids["train"],
            "validation": partition_ids["validation"],
            "test": partition_ids["test"],
            "test_status": TestStatus.LOCKED_UNCONSUMED.value,
            "purge_count": purge_count,
            "embargo_count": embargo_count,
            "structural_group_exclusion_count": structural_excluded,
            "prior_locked_exclusion_count": prior_locked,
            "prior_consumed_exclusion_count": prior_consumed,
            "source_record_count": len(normalized),
            "eligible_split_pool_count": len(ordered),
            "train_boundary_timestamp": train_boundary.isoformat().replace("+00:00", "Z"),
            "test_boundary_timestamp": test_boundary.isoformat().replace("+00:00", "Z"),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        split_sha256 = hashlib.sha256(canonical).hexdigest()
        return SplitArtifact(
            split_id=f"split-{split_sha256[:16]}",
            split_sha256=split_sha256,
            source_bundle_sha256=source_bundle_sha256,
            train=SplitPartition("train", partition_ids["train"]),
            validation=SplitPartition("validation", partition_ids["validation"]),
            test=SplitPartition("test", partition_ids["test"]),
            test_status=TestStatus.LOCKED_UNCONSUMED,
            purge_count=purge_count,
            embargo_count=embargo_count,
            structural_group_exclusion_count=structural_excluded,
            prior_locked_exclusion_count=prior_locked,
            prior_consumed_exclusion_count=prior_consumed,
            source_record_count=len(normalized),
            eligible_split_pool_count=len(ordered),
            train_boundary_timestamp=payload["train_boundary_timestamp"],
            test_boundary_timestamp=payload["test_boundary_timestamp"],
        )

    @staticmethod
    def _coerce_row(row: DatasetRowRecord | Mapping[str, object]) -> DatasetRowRecord:
        if isinstance(row, DatasetRowRecord):
            return row
        if not isinstance(row, Mapping):
            raise TypeError("rows must contain DatasetRowRecord or mapping values")
        try:
            return DatasetRowRecord(
                dataset_row_id=str(row["dataset_row_id"]),
                setup_time=str(row["setup_time"]),
                close_time=str(row["close_time"]),
                structural_group_id=str(row["structural_group_id"]),
            )
        except KeyError as exc:
            raise Beta4AGateError("SPLIT_ROW_SCHEMA_MISMATCH", f"missing row field: {exc.args[0]}") from exc

    @staticmethod
    def _verify_unique_ids(rows: Sequence[DatasetRowRecord]) -> None:
        ids = [row.dataset_row_id for row in rows]
        if len(ids) != len(set(ids)):
            raise Beta4AGateError("DUPLICATE_DATASET_ROW_ID", "dataset_row_id values must be unique")
