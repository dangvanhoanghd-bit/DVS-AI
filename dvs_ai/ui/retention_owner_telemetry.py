from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Iterable

from dvs_ai.monitoring.thread_identity import capture_thread_identity


@dataclass
class _OwnerState:
    baseline_current: int = 0
    current_ids: set[int] = field(default_factory=set)
    added_total: int = 0
    released_total: int = 0
    evicted_total: int = 0
    cleared_total: int = 0
    peak_current: int = 0
    release_without_count_drop_total: int = 0
    container_replaced_total: int = 0
    previous_container_instance_id: int | None = None
    last_replacement_reason: str | None = None
    tuple_length_before: int | None = None
    tuple_length_after: int | None = None
    initialized: bool = False
    explicit_events: bool = False


@dataclass(frozen=True)
class OwnerDescriptor:
    container_name: str
    owner_class: str
    owner_path: str
    bounded_limit: int | None
    resolve_owner: Callable[[Any], Any]
    resolve_container: Callable[[Any], Any]
    iter_payloads: Callable[[Any], Iterable[Any]]
    container_type: str | None = None
    retention_policy: str | None = None


class RetentionOwnerTelemetry:
    """RC6.4.7F-r1 mutation-site and direct-owner telemetry.

    Telemetry stores integer identities and counters only. It never retains
    observed payload objects, never calls gc.get_objects(), and never reprs or
    serializes domain objects.
    """

    def __init__(self, *, root: Any, runtime_session_id: str, output_path: str | Path):
        self._root = root
        self._runtime_session_id = str(runtime_session_id)
        self._output_path = Path(output_path)
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._states: dict[str, _OwnerState] = {}
        self._descriptors: list[OwnerDescriptor] = []
        # Telemetry must never block the operational pipeline.  A normal Lock is
        # retained for short state mutations, but every acquisition is fail-open.
        self._lock = threading.Lock()
        self._last_cycle_index = -1
        self._lock_busy_drop_total = 0
        self._lock_busy_by_operation: dict[str, int] = {}
        self._lock_wait_max_ms = 0.0
        self._gui_thread_id = threading.get_ident()
        self._enabled = str(
            os.environ.get("DVS_FORENSIC_MODE", "0")
        ).strip().lower() in {"1", "true", "yes", "on"}

    def _try_acquire(self, operation: str) -> tuple[bool, float]:
        started = time.perf_counter_ns()
        acquired = self._lock.acquire(blocking=False)
        wait_ms = (time.perf_counter_ns() - started) / 1_000_000.0
        self._lock_wait_max_ms = max(self._lock_wait_max_ms, wait_ms)
        if not acquired:
            self._lock_busy_drop_total += 1
            key = str(operation)
            self._lock_busy_by_operation[key] = self._lock_busy_by_operation.get(key, 0) + 1
        return acquired, wait_ms

    def diagnostics(self) -> dict[str, Any]:
        if not self._enabled:
            return {
                "enabled": False,
                "profile": "RC6.19-CLEAN",
                **capture_thread_identity(self._gui_thread_id),
            }
        return {
            "lock_busy_drop_total": int(self._lock_busy_drop_total),
            "lock_busy_by_operation": dict(self._lock_busy_by_operation),
            "lock_wait_max_ms": round(float(self._lock_wait_max_ms), 6),
            "lock_type": type(self._lock).__name__,
            "acquisition_mode": "non_blocking_fail_open",
            **capture_thread_identity(self._gui_thread_id),
        }

    def register(self, descriptor: OwnerDescriptor) -> None:
        if any(item.container_name == descriptor.container_name for item in self._descriptors):
            raise ValueError(f"duplicate owner descriptor: {descriptor.container_name}")
        self._descriptors.append(descriptor)
        self._states[descriptor.container_name] = _OwnerState()

    @staticmethod
    def _payload_ids(payloads: Iterable[Any]) -> set[int]:
        ids: set[int] = set()
        for item in payloads:
            if item is not None:
                ids.add(id(item))
        return ids

    @staticmethod
    def _rss_bytes() -> int | None:
        try:
            import psutil  # type: ignore
            return int(psutil.Process(os.getpid()).memory_info().rss)
        except Exception:
            return None

    def record_mutation(
        self,
        container_name: str,
        *,
        operation: str,
        count_before: int,
        count_after: int,
        item_count: int = 1,
    ) -> None:
        """Record append/pop/clear exactly at the mutation site."""
        if not self._enabled:
            return
        if not self._enabled:
            return
        state = self._states.get(container_name)
        if state is None:
            return
        before, after = int(count_before), int(count_after)
        n = max(0, int(item_count))
        acquired, _wait_ms = self._try_acquire(f"mutation:{container_name}:{operation}")
        if not acquired:
            return
        try:
            if not state.initialized:
                state.baseline_current = before
                state.current_ids = set()
                state.initialized = True
            state.explicit_events = True
            if operation in {"append", "extend", "enqueue"}:
                state.added_total += n
            elif operation in {"pop", "popleft", "dequeue", "remove"}:
                state.released_total += n
                if n and after >= before:
                    state.release_without_count_drop_total += 1
            elif operation == "clear":
                state.cleared_total += n
                state.released_total += n
                if n and after >= before:
                    state.release_without_count_drop_total += 1
            elif operation == "evict":
                state.evicted_total += n
                if n and after >= before:
                    state.release_without_count_drop_total += 1
            state.peak_current = max(state.peak_current, before, after)
        finally:
            self._lock.release()

    def record_container_replaced(
        self,
        container_name: str,
        *,
        old_container: Any,
        new_container: Any,
        replacement_reason: str,
        flatten_groups: bool = False,
        account_payload_delta: bool = True,
    ) -> None:
        """Record assignment of a new container at the exact assignment site."""
        state = self._states.get(container_name)
        if state is None:
            return
        before = 0 if old_container is None else len(old_container)
        after = 0 if new_container is None else len(new_container)
        def replacement_payloads(value: Any):
            if isinstance(value, dict):
                return tuple(value.values())
            groups = tuple(value or ())
            if flatten_groups:
                return tuple(item for group in groups for item in (group if isinstance(group, (list, tuple)) else (group,)))
            return groups
        old_ids = self._payload_ids(replacement_payloads(old_container))
        new_ids = self._payload_ids(replacement_payloads(new_container))
        acquired, _wait_ms = self._try_acquire(f"replace:{container_name}")
        if not acquired:
            return
        try:
            if not state.initialized:
                state.baseline_current = len(old_ids)
                state.current_ids = old_ids
                state.initialized = True
            state.explicit_events = True
            state.container_replaced_total += 1
            state.previous_container_instance_id = None if old_container is None else id(old_container)
            state.last_replacement_reason = str(replacement_reason)
            state.tuple_length_before = before
            state.tuple_length_after = after
            if account_payload_delta:
                state.added_total += len(new_ids - old_ids)
                state.released_total += len(old_ids - new_ids)
            state.peak_current = max(state.peak_current, before, after)
        finally:
            self._lock.release()

    def snapshot(self, *, cycle_index: int) -> list[dict[str, Any]]:
        if not self._enabled:
            return []
        cycle_index = int(cycle_index)
        if cycle_index == self._last_cycle_index:
            return []
        self._last_cycle_index = cycle_index
        now_monotonic = time.monotonic()
        now_utc = datetime.now(timezone.utc).isoformat()
        rss_bytes = self._rss_bytes()
        records: list[dict[str, Any]] = []

        for descriptor in self._descriptors:
            owner = descriptor.resolve_owner(self._root)
            container = descriptor.resolve_container(owner) if owner is not None else None
            payload_ids = self._payload_ids(descriptor.iter_payloads(container))
            current_count = len(payload_ids)
            state = self._states[descriptor.container_name]
            acquired, lock_wait_ms = self._try_acquire(f"snapshot:{descriptor.container_name}")
            if not acquired:
                continue
            try:
                if not state.initialized:
                    state.baseline_current = current_count
                    state.current_ids = payload_ids
                    state.peak_current = max(state.peak_current, current_count)
                    state.initialized = True
                elif not state.explicit_events:
                    # Snapshot-diff fallback only for owners without mutation-site hooks.
                    state.added_total += len(payload_ids - state.current_ids)
                    state.released_total += len(state.current_ids - payload_ids)
                state.current_ids = payload_ids
                state.peak_current = max(state.peak_current, current_count)
                expected_current = state.baseline_current + state.added_total - state.released_total - state.evicted_total
                record = {
                    "event": "retention_owner_snapshot",
                    "timestamp_utc": now_utc,
                    "timestamp_monotonic": round(now_monotonic, 6),
                    "runtime_session_id": self._runtime_session_id,
                    **capture_thread_identity(self._gui_thread_id),
                    "cycle_index": cycle_index,
                    "container_name": descriptor.container_name,
                    "owner_class": type(owner).__name__ if owner is not None else descriptor.owner_class,
                    "owner_path": descriptor.owner_path,
                    "owner_instance_id": hex(id(owner)) if owner is not None else None,
                    "container_instance_id": hex(id(container)) if container is not None else None,
                    "previous_container_instance_id": None if state.previous_container_instance_id is None else hex(state.previous_container_instance_id),
                    "container_type": descriptor.container_type or (type(container).__name__ if container is not None else "NoneType"),
                    "retention_policy": descriptor.retention_policy,
                    "bounded_limit": descriptor.bounded_limit,
                    "baseline_current": state.baseline_current,
                    "current_count": current_count,
                    "peak_current": state.peak_current,
                    "estimated_payload_items": len(payload_ids),
                    "added_total": state.added_total,
                    "released_total": state.released_total,
                    "cleared_total": state.cleared_total,
                    "evicted_total": state.evicted_total,
                    "expected_current": expected_current,
                    "accounting_delta": current_count - expected_current,
                    "release_without_count_drop_total": state.release_without_count_drop_total,
                    "container_replaced_total": state.container_replaced_total,
                    "replacement_reason": state.last_replacement_reason,
                    "tuple_length_before": state.tuple_length_before,
                    "tuple_length_after": state.tuple_length_after,
                    "oldest_item_age_ms": None,
                    "rss_bytes_nearest": rss_bytes,
                    "rss_sample_age_ms": 0 if rss_bytes is not None else None,
                    "measurement_mode": "mutation_site_or_direct_owner_integer_identity",
                    "telemetry_lock_acquire_wait_ms": round(lock_wait_ms, 6),
                    "telemetry_lock_busy_drop_total": int(self._lock_busy_drop_total),
                    "telemetry_lock_busy_by_operation": dict(self._lock_busy_by_operation),
                }
            finally:
                self._lock.release()
            records.append(record)

        if records:
            with self._output_path.open("a", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return records
