from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
import itertools
import json
import os
from pathlib import Path
import sys
import threading
import time
from collections.abc import Mapping
from typing import Any
import uuid


class _BudgetExceeded(RuntimeError):
    pass


class SelectedDeepSizer:
    """Bounded selected-deep estimator for known Python/data payloads.

    This is deliberately not a full heap census. It does not call gc.get_objects(),
    does not use repr(), and stops at explicit depth/node/time budgets. Object IDs
    are used only within one measurement to avoid double counting.
    """

    def __init__(self, *, max_depth: int = 8, max_nodes: int = 60000, budget_ms: float = 180.0):
        self.max_depth = int(max_depth)
        self.max_nodes = int(max_nodes)
        self.deadline = time.perf_counter() + max(1.0, float(budget_ms)) / 1000.0
        self.seen: set[int] = set()
        self.nodes = 0
        self.components: dict[str, int] = {}
        self.truncated = False
        self.truncation_reason: str | None = None

    def _check(self) -> None:
        if self.nodes >= self.max_nodes:
            raise _BudgetExceeded("max_nodes")
        if time.perf_counter() >= self.deadline:
            raise _BudgetExceeded("time_budget")

    def _add_component(self, name: str, size: int) -> None:
        self.components[name] = self.components.get(name, 0) + max(0, int(size))

    def size(self, obj: Any, depth: int = 0) -> int:
        if obj is None:
            return 0
        try:
            self._check()
            oid = id(obj)
            if oid in self.seen:
                return 0
            self.seen.add(oid)
            self.nodes += 1
            shallow = int(sys.getsizeof(obj, 0))
            self._add_component(type(obj).__name__, shallow)
            if depth >= self.max_depth:
                return shallow

            mod = type(obj).__module__
            name = type(obj).__name__
            if mod.startswith("pandas"):
                deep = shallow
                try:
                    if name == "DataFrame":
                        deep = int(obj.memory_usage(index=True, deep=True).sum())
                    elif name == "Series":
                        deep = int(obj.memory_usage(index=True, deep=True))
                    elif name == "Index":
                        deep = int(obj.memory_usage(deep=True))
                except Exception:
                    pass
                self._add_component("pandas_deep_extra", max(0, deep - shallow))
                return deep

            if mod.startswith("numpy") and hasattr(obj, "nbytes"):
                try:
                    native = int(obj.nbytes)
                except Exception:
                    native = 0
                self._add_component("numpy_buffer_bytes", native)
                return shallow + native

            if isinstance(obj, (str, bytes, bytearray, memoryview, int, float, bool, complex)):
                return shallow
            total = shallow
            if isinstance(obj, Mapping):
                # list(...) gives a stable iteration vector without deep-copying values.
                # Optimistic version validation below invalidates the request if the
                # owner changes while the worker is measuring.
                for key, value in list(obj.items()):
                    total += self.size(key, depth + 1)
                    total += self.size(value, depth + 1)
                return total
            if isinstance(obj, (list, tuple, set, frozenset)):
                for item in list(obj):
                    total += self.size(item, depth + 1)
                return total
            if is_dataclass(obj) and not isinstance(obj, type):
                for f in fields(obj):
                    try:
                        value = getattr(obj, f.name)
                    except Exception:
                        continue
                    total += self.size(value, depth + 1)
                return total
            d = getattr(obj, "__dict__", None)
            if isinstance(d, dict) and not mod.startswith(("PySide6", "shiboken6")):
                total += self.size(d, depth + 1)
            return total
        except _BudgetExceeded as exc:
            self.truncated = True
            self.truncation_reason = str(exc)
            return 0
        except Exception:
            return 0


def _owner_version(obj: Any) -> dict[str, Any]:
    """Cheap optimistic version token; never walks the deep object graph."""
    token: dict[str, Any] = {"object_id": id(obj), "type": type(obj).__name__}
    try:
        token["length"] = len(obj)
    except Exception:
        token["length"] = None
    if isinstance(obj, Mapping):
        try:
            items = list(obj.items())
            token["edge_fingerprint"] = hash(tuple((id(k), id(v)) for k, v in items))
        except Exception:
            token["edge_fingerprint"] = None
    elif isinstance(obj, (list, tuple)):
        try:
            token["edge_fingerprint"] = hash(tuple(id(v) for v in obj))
        except Exception:
            token["edge_fingerprint"] = None
    else:
        token["edge_fingerprint"] = None
    return token


@dataclass
class _SnapshotRequest:
    request_id: str
    generation: int
    cycle_index: int
    submit_thread_id: int
    gui_thread_id: int
    submit_monotonic: float
    results: Any
    current_analysis: Any
    pending_analysis: Any
    versions_before: dict[str, dict[str, Any]]

    def release_references(self) -> None:
        self.results = None
        self.current_analysis = None
        self.pending_analysis = None
        self.versions_before = {}


class _SnapshotCancelled(RuntimeError):
    """Internal cooperative-cancellation marker for shutdown."""


class PayloadFootprintTelemetry:
    """Single-flight, fail-open payload footprint worker.

    The GUI thread only records a submit event and starts a daemon worker. If one
    measurement is already active, the request is explicitly BUSY_DROP; no queue
    and no hidden reference backlog are permitted.

    Ownership strategy: optimistic version validation. The worker records shallow
    owner version tokens before and after measurement. Measurements are marked
    invalidated when an owner changes during traversal. This avoids pretending a
    mutable live graph is immutable while keeping submit overhead bounded.
    """

    SCHEMA = "dvs.runtime.payload_footprint.v2"

    def __init__(self, output_path: str | Path = "artifacts/runtime/payload_footprint.jsonl"):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._single_flight = threading.Lock()
        self._sequence = itertools.count(1)
        self._generation = itertools.count(1)
        self._gui_thread_id = threading.get_ident()
        self._busy_drop_total = 0
        self._lifecycle_lock = threading.Lock()
        self._active_worker: threading.Thread | None = None
        self._active_request_id: str | None = None
        self._active_generation: int | None = None
        self._shutdown_requested = threading.Event()

    def _thread_fields(self) -> dict[str, Any]:
        tid = threading.get_ident()
        return {
            "measurement_thread_id": tid,
            "gui_thread_id": self._gui_thread_id,
            "thread_name": threading.current_thread().name,
            "is_gui_thread": tid == self._gui_thread_id,
        }

    def _write(self, payload: dict[str, Any]) -> None:
        with self._write_lock:
            record = {
                "schema_version": self.SCHEMA,
                "sequence": next(self._sequence),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "timestamp_monotonic": round(time.monotonic(), 6),
                **self._thread_fields(),
                **payload,
            }
            encoded = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            fd = os.open(self.output_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
            try:
                os.write(fd, encoded)
            finally:
                os.close(fd)

    def _check_shutdown_requested(self) -> None:
        if self._shutdown_requested.is_set():
            raise _SnapshotCancelled("payload footprint shutdown requested")

    def shutdown(self, timeout_s: float = 5.0) -> bool:
        """Request cooperative stop and wait a bounded time for the active worker.

        Returns True only when no payload worker remains alive. A timeout is
        explicitly reported and must be treated by the caller as shutdown failure.
        """
        timeout_s = max(0.0, float(timeout_s))
        started = time.monotonic()
        self._shutdown_requested.set()
        with self._lifecycle_lock:
            worker = self._active_worker
            request_id = self._active_request_id
            generation = self._active_generation
        self._write({
            "event": "payload_footprint_shutdown_requested",
            "request_id": request_id,
            "generation": generation,
            "timeout_ms": round(timeout_s * 1000.0, 3),
            "worker_alive": bool(worker is not None and worker.is_alive()),
        })
        if worker is None or not worker.is_alive():
            self._write({
                "event": "payload_footprint_shutdown_completed",
                "request_id": request_id,
                "generation": generation,
                "wait_ms": round((time.monotonic() - started) * 1000.0, 3),
                "worker_alive": False,
            })
            return True
        if worker is threading.current_thread():
            self._write({
                "event": "payload_footprint_shutdown_failed",
                "request_id": request_id,
                "generation": generation,
                "reason": "shutdown_called_from_active_worker",
                "worker_alive": True,
            })
            return False
        worker.join(timeout=timeout_s)
        alive = worker.is_alive()
        self._write({
            "event": "payload_footprint_shutdown_timeout" if alive else "payload_footprint_shutdown_completed",
            "request_id": request_id,
            "generation": generation,
            "wait_ms": round((time.monotonic() - started) * 1000.0, 3),
            "timeout_ms": round(timeout_s * 1000.0, 3),
            "worker_alive": alive,
        })
        return not alive

    def _measure(self, owner_path: str, obj: Any, *, request: _SnapshotRequest,
                 max_nodes: int, budget_ms: float) -> dict[str, Any]:
        started = time.perf_counter()
        sizer = SelectedDeepSizer(max_depth=8, max_nodes=max_nodes, budget_ms=budget_ms)
        shallow = int(sys.getsizeof(obj, 0)) if obj is not None else 0
        estimated = sizer.size(obj)
        token_count = len(obj) if isinstance(obj, Mapping) else (0 if obj is None else 1)
        result = {
            "event": "owner_footprint_snapshot",
            "request_id": request.request_id,
            "generation": request.generation,
            "cycle_index": request.cycle_index,
            "owner_path": owner_path,
            "object_present": obj is not None,
            "object_count": int(token_count),
            "shallow_bytes": shallow,
            "estimated_selected_deep_bytes": int(estimated),
            "visited_nodes": int(sizer.nodes),
            "truncated": bool(sizer.truncated),
            "truncation_reason": sizer.truncation_reason,
            "max_nodes": int(max_nodes),
            "budget_ms": float(budget_ms),
            "measurement_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "component_bytes": dict(sorted(sizer.components.items(), key=lambda kv: kv[1], reverse=True)[:24]),
        }
        self._write(result)
        return result

    def _run_request(self, request: _SnapshotRequest) -> None:
        start_mono = time.monotonic()
        self._write({
            "event": "snapshot_started",
            "request_id": request.request_id,
            "generation": request.generation,
            "cycle_index": request.cycle_index,
            "submit_thread_id": request.submit_thread_id,
            "submit_monotonic": request.submit_monotonic,
            "start_monotonic": start_mono,
            "queue_depth": 0,
            "ownership_contract": "optimistic_version_validation",
        })
        status = "finished"
        failure_type = None
        failure_message = None
        versions_after: dict[str, dict[str, Any]] = {}
        invalidated_owners: list[str] = []
        measurement_finished = start_mono
        try:
            self._check_shutdown_requested()
            self._measure("MainWindow._truth_dashboard_pending_analysis", request.pending_analysis,
                          request=request, max_nodes=18000, budget_ms=75.0)
            self._check_shutdown_requested()
            self._measure("MainWindow.current_analysis", request.current_analysis,
                          request=request, max_nodes=18000, budget_ms=75.0)
            self._check_shutdown_requested()
            if request.cycle_index <= 2 or request.cycle_index % 5 == 0:
                self._measure("MainWindow.results", request.results,
                              request=request, max_nodes=60000, budget_ms=220.0)
            else:
                self._write({
                    "event": "owner_footprint_skipped",
                    "request_id": request.request_id,
                    "generation": request.generation,
                    "cycle_index": request.cycle_index,
                    "owner_path": "MainWindow.results",
                    "reason": "sample_every_5_cycles",
                })
            versions_after = {
                "results": _owner_version(request.results),
                "current_analysis": _owner_version(request.current_analysis),
                "pending_analysis": _owner_version(request.pending_analysis),
            }
            invalidated_owners = [
                name for name, before in request.versions_before.items()
                if versions_after.get(name) != before
            ]
            if invalidated_owners:
                status = "invalidated_owner_changed"
        except _SnapshotCancelled as exc:
            status = "cancelled_shutdown"
            failure_type = type(exc).__name__
            failure_message = str(exc)
        except Exception as exc:
            status = "failed"
            failure_type = type(exc).__name__
            failure_message = str(exc)
        finally:
            measurement_finished = time.monotonic()
            request.release_references()
            reference_release_mono = time.monotonic()
            release_ms = max(0.0, (reference_release_mono - measurement_finished) * 1000.0)
            if status == "failed":
                terminal_event = "snapshot_failed"
            elif status == "cancelled_shutdown":
                terminal_event = "snapshot_cancelled"
            else:
                terminal_event = "snapshot_finished"
            self._write({
                "event": terminal_event,
                "request_id": request.request_id,
                "generation": request.generation,
                "cycle_index": request.cycle_index,
                "status": status,
                "measurement_finished_monotonic": measurement_finished,
                "reference_release_monotonic": reference_release_mono,
                "reference_release_ms": round(release_ms, 6),
                "worker_measurement_ms": round((measurement_finished - start_mono) * 1000.0, 3),
                "invalidated_owners": invalidated_owners,
                "versions_after": versions_after,
                "failure_type": failure_type,
                "failure_message": failure_message,
                "queue_depth": 0,
                "busy_drop_total": self._busy_drop_total,
            })
            with self._lifecycle_lock:
                if self._active_worker is threading.current_thread():
                    self._active_worker = None
                    self._active_request_id = None
                    self._active_generation = None
            self._single_flight.release()

    def snapshot(self, *, cycle_index: int, results: Any, current_analysis: Any, pending_analysis: Any) -> bool:
        """Submit a non-blocking single-flight measurement request.

        Returns True when accepted, False when explicitly dropped because the
        worker is already active. Every call emits exactly one snapshot_submit.
        """
        submit_started = time.perf_counter()
        generation = next(self._generation)
        request_id = uuid.uuid4().hex
        submit_thread_id = threading.get_ident()
        submit_mono = time.monotonic()
        if self._shutdown_requested.is_set():
            submit_callback_ms = (time.perf_counter() - submit_started) * 1000.0
            self._write({
                "event": "snapshot_submit",
                "request_id": request_id,
                "generation": generation,
                "cycle_index": int(cycle_index),
                "submit_thread_id": submit_thread_id,
                "submit_monotonic": submit_mono,
                "queue_depth": 0,
                "accepted": False,
                "outcome": "shutdown_rejected",
                "snapshot_submit_callback_ms": round(submit_callback_ms, 6),
                "busy_drop_total": self._busy_drop_total,
            })
            return False
        accepted = self._single_flight.acquire(blocking=False)
        if not accepted:
            self._busy_drop_total += 1
        submit_callback_ms = (time.perf_counter() - submit_started) * 1000.0
        self._write({
            "event": "snapshot_submit",
            "request_id": request_id,
            "generation": generation,
            "cycle_index": int(cycle_index),
            "submit_thread_id": submit_thread_id,
            "submit_monotonic": submit_mono,
            "queue_depth": 0 if accepted else 1,
            "accepted": accepted,
            "outcome": "accepted" if accepted else "busy_drop",
            "snapshot_submit_callback_ms": round(submit_callback_ms, 6),
            "busy_drop_total": self._busy_drop_total,
        })
        if not accepted:
            self._write({
                "event": "snapshot_busy_drop",
                "request_id": request_id,
                "generation": generation,
                "cycle_index": int(cycle_index),
                "submit_thread_id": submit_thread_id,
                "queue_depth": 1,
                "busy_drop_total": self._busy_drop_total,
            })
            return False

        request = _SnapshotRequest(
            request_id=request_id,
            generation=generation,
            cycle_index=int(cycle_index),
            submit_thread_id=submit_thread_id,
            gui_thread_id=self._gui_thread_id,
            submit_monotonic=submit_mono,
            results=results,
            current_analysis=current_analysis,
            pending_analysis=pending_analysis,
            versions_before={
                "results": _owner_version(results),
                "current_analysis": _owner_version(current_analysis),
                "pending_analysis": _owner_version(pending_analysis),
            },
        )
        worker = threading.Thread(
            target=self._run_request,
            args=(request,),
            name=f"PayloadFootprintWorker-{generation}",
            daemon=False,
        )
        with self._lifecycle_lock:
            self._active_worker = worker
            self._active_request_id = request_id
            self._active_generation = generation
        try:
            worker.start()
        except Exception:
            with self._lifecycle_lock:
                if self._active_worker is worker:
                    self._active_worker = None
                    self._active_request_id = None
                    self._active_generation = None
            request.release_references()
            self._single_flight.release()
            raise
        return True


PAYLOAD_FOOTPRINT_TELEMETRY = PayloadFootprintTelemetry()
