from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, TYPE_CHECKING

from .contracts import HoldoutConsumptionRecord, TestStatus
from .errors import Beta4AGateError

if TYPE_CHECKING:
    from .dataset_split import SplitArtifact


@dataclass(frozen=True, slots=True)
class LockedTestRegistryEntry:
    dataset_row_id: str
    status: TestStatus
    source_split_sha256: str


class LockedTestRowRegistry:
    """Derived-only registry rebuilt from immutable split and consumption artifacts."""

    def rebuild(
        self,
        split_artifacts: Iterable["SplitArtifact"],
        consumption_records: Iterable[HoldoutConsumptionRecord],
    ) -> tuple[LockedTestRegistryEntry, ...]:
        splits = tuple(split_artifacts)
        records = tuple(consumption_records)
        consumed_splits = {record.split_sha256 for record in records}
        split_hashes = {split.split_sha256 for split in splits}
        orphaned = consumed_splits - split_hashes
        if orphaned:
            raise Beta4AGateError(
                "SPLIT_ARTIFACT_VERIFICATION_FAILED_EXCLUDED",
                f"consumption records reference unknown split(s): {sorted(orphaned)}",
            )

        entries: dict[str, LockedTestRegistryEntry] = {}
        role_history: dict[str, tuple[str, str]] = {}
        for split in sorted(splits, key=lambda item: item.split_sha256):
            for role, row_ids in (("TRAIN", split.train.dataset_row_ids),
                                  ("VALIDATION", split.validation.dataset_row_ids),
                                  ("TEST", split.test.dataset_row_ids)):
                for row_id in row_ids:
                    previous = role_history.get(row_id)
                    if previous is not None:
                        previous_role, previous_split = previous
                        if previous_split != split.split_sha256 and (previous_role == "TEST" or role == "TEST"):
                            raise Beta4AGateError(
                                "LOCK_HISTORY_CONFLICT",
                                f"row {row_id} crosses locked TEST history: "
                                f"{previous_role}@{previous_split} -> {role}@{split.split_sha256}",
                            )
                    else:
                        role_history[row_id] = (role, split.split_sha256)

            status = TestStatus.CONSUMED if split.split_sha256 in consumed_splits else TestStatus.LOCKED_UNCONSUMED
            for row_id in split.test.dataset_row_ids:
                candidate = LockedTestRegistryEntry(row_id, status, split.split_sha256)
                existing = entries.get(row_id)
                if existing is None:
                    entries[row_id] = candidate
                    continue
                if existing.source_split_sha256 != candidate.source_split_sha256:
                    raise Beta4AGateError(
                        "LOCK_HISTORY_CONFLICT",
                        f"test row {row_id} appears in multiple split artifacts",
                    )
                if existing.status is not candidate.status:
                    raise Beta4AGateError(
                        "LOCK_HISTORY_CONFLICT",
                        f"conflicting status history for test row {row_id}",
                    )
        return tuple(entries[row_id] for row_id in sorted(entries))
