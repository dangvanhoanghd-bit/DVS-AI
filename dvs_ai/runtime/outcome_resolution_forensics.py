"""DVS AI v2.4.3 RC6.7 — Outcome Resolution Forensics.

Append-only observability. This module does not dispatch, cancel, interrupt,
quit, wait, retry, or alter Outcome Resolution state.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PATH = Path("artifacts/runtime/outcome_resolution_forensics.jsonl")
_LOCK = threading.Lock()
_SEQUENCE = 0


def _next_sequence() -> int:
    global _SEQUENCE
    with _LOCK:
        _SEQUENCE += 1
        return _SEQUENCE


def _safe_call(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def coordinator_snapshot(coordinator: object | None) -> dict[str, Any]:
    if coordinator is None:
        return {}
    thread = _safe_call(lambda: getattr(coordinator, "_thread", None), None)
    worker = _safe_call(lambda: getattr(coordinator, "_worker", None), None)
    cancel_event = _safe_call(lambda: getattr(coordinator, "_cancel_event", None), None)
    return {
        "coordinator_active": _safe_call(
            lambda: bool(getattr(coordinator, "_active", False)), None
        ),
        "coordinator_pending_refresh": _safe_call(
            lambda: bool(getattr(coordinator, "_pending_refresh", False)), None
        ),
        "coordinator_shutdown_requested": _safe_call(
            lambda: bool(getattr(coordinator, "_shutdown_requested", False)), None
        ),
        "coordinator_closed": _safe_call(
            lambda: bool(getattr(coordinator, "_closed", False)), None
        ),
        "coordinator_dispatch_count": _safe_call(
            lambda: int(getattr(coordinator, "_forensic_dispatch_count", 0)), None
        ),
        "thread_present": thread is not None,
        "thread_running": _safe_call(
            lambda: bool(thread.isRunning()) if thread is not None else None, None
        ),
        "thread_finished": _safe_call(
            lambda: bool(thread.isFinished()) if thread is not None else None, None
        ),
        "thread_interruption_requested": _safe_call(
            lambda: bool(thread.isInterruptionRequested()) if thread is not None else None,
            None,
        ),
        "thread_object_name": _safe_call(
            lambda: thread.objectName() if thread is not None else None, None
        ),
        "worker_present": worker is not None,
        "worker_active_stage": _safe_call(
            lambda: getattr(worker, "active_stage", None), None
        ),
        "worker_active_run_id": _safe_call(
            lambda: getattr(worker, "active_run_id", None), None
        ),
        "worker_cycle_started_ns": _safe_call(
            lambda: getattr(worker, "cycle_started_ns", None), None
        ),
        "worker_stage_started_ns": _safe_call(
            lambda: getattr(worker, "stage_started_ns", None), None
        ),
        "worker_deadline_monotonic": _safe_call(
            lambda: getattr(worker, "deadline_monotonic", None), None
        ),
        "cancel_event_set": _safe_call(
            lambda: bool(cancel_event.is_set()) if cancel_event is not None else None,
            None,
        ),
    }


def record_outcome_resolution(
    event: str,
    *,
    coordinator: object | None = None,
    **extra: Any,
) -> None:
    now_ns = time.monotonic_ns()
    snapshot = coordinator_snapshot(coordinator)
    cycle_started_ns = snapshot.get("worker_cycle_started_ns")
    stage_started_ns = snapshot.get("worker_stage_started_ns")
    row = {
        "schema_version": "dvs.runtime.outcome_resolution_forensics.v1",
        "event": str(event),
        "sequence": _next_sequence(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_ns": now_ns,
        "pid": os.getpid(),
        "thread_ident": threading.get_ident(),
        **snapshot,
        "worker_cycle_elapsed_ms": (
            round((now_ns - int(cycle_started_ns)) / 1_000_000.0, 3)
            if cycle_started_ns else None
        ),
        "worker_stage_elapsed_ms": (
            round((now_ns - int(stage_started_ns)) / 1_000_000.0, 3)
            if stage_started_ns else None
        ),
        **extra,
    }
    # RC6.17 (causal fix): the RC6.16-r1 independent GUI hang watchdog
    # directly caught the GUI thread's Python stack inside this
    # synchronous open/write/flush sequence, reached via
    # outcome_resolution_timer (60s QTimer) -> coordinator.request_
    # resolution() -> here (observed_lag_ms=2281). Enqueue instead of
    # writing inline; a dedicated background thread performs the actual
    # disk I/O. Output format (path, JSON encoding, one line per record)
    # is unchanged.
    try:
        from dvs_ai.runtime.async_jsonl_writer import enqueue_jsonl_write
        enqueue_jsonl_write(_PATH, row)
    except Exception:
        pass
