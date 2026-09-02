"""DVS AI v2.4.3 RC6.2 — Learning Refresh Lifecycle Telemetry.

Observability only. This module does not request interruption, quit, wait,
terminate, reschedule, cancel, or otherwise alter Learning Refresh behavior.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = "dvs.runtime.learning_refresh_lifecycle.v1"
_OUT_PATH = Path("artifacts/runtime/learning_refresh_lifecycle.jsonl")
_WRITE_LOCK = threading.Lock()
_SEQUENCE = 0


def _next_sequence() -> int:
    global _SEQUENCE
    with _WRITE_LOCK:
        _SEQUENCE += 1
        return _SEQUENCE


def _safe_call(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _thread_snapshot(thread: object | None) -> dict[str, Any]:
    if thread is None:
        return {
            "thread_present": False,
            "thread_running": None,
            "thread_finished": None,
            "thread_interruption_requested": None,
            "thread_object_name": None,
            "thread_python_id": None,
        }
    return {
        "thread_present": True,
        "thread_running": _safe_call(lambda: bool(thread.isRunning()), None),
        "thread_finished": _safe_call(lambda: bool(thread.isFinished()), None),
        "thread_interruption_requested": _safe_call(
            lambda: bool(thread.isInterruptionRequested()), None
        ),
        "thread_object_name": _safe_call(lambda: thread.objectName(), None),
        "thread_python_id": hex(id(thread)),
    }


def _worker_snapshot(worker: object | None) -> dict[str, Any]:
    if worker is None:
        return {
            "worker_present": False,
            "worker_python_id": None,
            "active_stage": None,
            "refresh_active": None,
            "refresh_cycle": None,
            "stop_requested": None,
            "refresh_elapsed_ms": None,
            "active_stage_elapsed_ms": None,
        }

    now_ns = time.monotonic_ns()
    refresh_started_ns = getattr(worker, "_lifecycle_refresh_started_ns", None)
    stage_started_ns = getattr(worker, "_lifecycle_stage_started_ns", None)
    stop_event = getattr(worker, "_stop_requested", None)

    return {
        "worker_present": True,
        "worker_python_id": hex(id(worker)),
        "active_stage": getattr(worker, "_lifecycle_active_stage", None),
        "refresh_active": bool(getattr(worker, "_lifecycle_refresh_active", False)),
        "refresh_cycle": int(getattr(worker, "_lifecycle_refresh_cycle", 0) or 0),
        "stop_requested": (
            bool(stop_event.is_set()) if stop_event is not None else None
        ),
        "stop_requested_monotonic_ns": getattr(
            worker, "_lifecycle_stop_requested_ns", None
        ),
        "refresh_started_monotonic_ns": refresh_started_ns,
        "stage_started_monotonic_ns": stage_started_ns,
        "last_completed_stage": getattr(
            worker, "_lifecycle_last_completed_stage", None
        ),
        "last_completed_stage_monotonic_ns": getattr(
            worker, "_lifecycle_last_completed_stage_ns", None
        ),
        "refresh_elapsed_ms": (
            round((now_ns - int(refresh_started_ns)) / 1_000_000.0, 3)
            if refresh_started_ns
            else None
        ),
        "active_stage_elapsed_ms": (
            round((now_ns - int(stage_started_ns)) / 1_000_000.0, 3)
            if stage_started_ns
            else None
        ),
    }


def record_learning_refresh_event(
    event: str,
    *,
    worker: object | None = None,
    thread: object | None = None,
    **extra: Any,
) -> None:
    row = {
        "schema_version": _SCHEMA,
        "event": str(event),
        "sequence": _next_sequence(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_ns": time.monotonic_ns(),
        "pid": os.getpid(),
        "thread_ident": threading.get_ident(),
        **_worker_snapshot(worker),
        **_thread_snapshot(thread),
        **extra,
    }
    try:
        _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        with _WRITE_LOCK:
            with _OUT_PATH.open("a", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
    except Exception:
        # Forensics must never alter runtime control flow.
        pass


def snapshot_learning_refresh(
    *,
    worker: object | None,
    thread: object | None,
    event: str,
    **extra: Any,
) -> None:
    record_learning_refresh_event(
        event,
        worker=worker,
        thread=thread,
        **extra,
    )
