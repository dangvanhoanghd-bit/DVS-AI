"""DVS AI v2.4.3 RC6.4 — Learning Refresh Dispatch Forensics.

Observation only. This module does not schedule, suppress, cancel, retry,
interrupt, quit, wait for, or otherwise alter Learning Refresh behavior.
"""

from __future__ import annotations

import inspect
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = "dvs.runtime.learning_dispatch_forensics.v1"
_PATH = Path("artifacts/runtime/learning_dispatch_forensics.jsonl")
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


def _caller_frames(limit: int = 8) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    try:
        stack = inspect.stack(context=0)
        for frame_info in stack[2 : 2 + max(1, int(limit))]:
            filename = str(frame_info.filename).replace("\\", "/")
            frames.append(
                {
                    "function": str(frame_info.function),
                    "filename": filename,
                    "line": int(frame_info.lineno),
                }
            )
    except Exception:
        pass
    return frames


def _window_state(window: object | None) -> dict[str, Any]:
    if window is None:
        return {}
    thread = _safe_call(lambda: getattr(window, "_learning_thread", None), None)
    worker = _safe_call(lambda: getattr(window, "_learning_worker", None), None)
    return {
        "is_closing": _safe_call(lambda: bool(window.is_closing), None),
        "shutdown_registry_waiting": _safe_call(
            lambda: bool(getattr(window, "_shutdown_registry_waiting", False)), None
        ),
        "shutdown_pre_registry_complete": _safe_call(
            lambda: bool(getattr(window, "_shutdown_pre_registry_complete", False)), None
        ),
        "learning_refresh_running": _safe_call(
            lambda: bool(getattr(window, "_learning_refresh_running", False)), None
        ),
        "learning_refresh_pending": _safe_call(
            lambda: bool(getattr(window, "_learning_refresh_pending", False)), None
        ),
        "learning_thread_present": thread is not None,
        "learning_thread_running": _safe_call(
            lambda: bool(thread.isRunning()) if thread is not None else None, None
        ),
        "learning_thread_finished": _safe_call(
            lambda: bool(thread.isFinished()) if thread is not None else None, None
        ),
        "learning_thread_interruption_requested": _safe_call(
            lambda: bool(thread.isInterruptionRequested()) if thread is not None else None,
            None,
        ),
        "learning_thread_object_name": _safe_call(
            lambda: thread.objectName() if thread is not None else None, None
        ),
        "worker_refresh_active": _safe_call(
            lambda: bool(getattr(worker, "_lifecycle_refresh_active", False))
            if worker is not None
            else None,
            None,
        ),
        "worker_active_stage": _safe_call(
            lambda: getattr(worker, "_lifecycle_active_stage", None)
            if worker is not None
            else None,
            None,
        ),
        "dispatch_context": _safe_call(
            lambda: dict(getattr(window, "_learning_dispatch_context", {}) or {}), {}
        ),
        "gui_refresh_queue_size": _safe_call(
            lambda: len(getattr(window, "_gui_refresh_queue", ())), None
        ),
        "gui_refresh_pending_contains_learning": _safe_call(
            lambda: "refresh_learning_center"
            in getattr(window, "_gui_refresh_pending", set()),
            None,
        ),
    }


def record_learning_dispatch(
    event: str,
    *,
    window: object | None,
    source: str | None = None,
    reason: str | None = None,
    capture_stack: bool = False,
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
        "source": source,
        "reason": reason,
        **_window_state(window),
        **extra,
    }
    if capture_stack:
        row["caller_frames"] = _caller_frames()

    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        with _LOCK:
            with _PATH.open("a", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
    except Exception:
        pass


def infer_dispatch_source(
    window: object | None,
    *,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
) -> tuple[str, str | None]:
    context = _safe_call(
        lambda: dict(getattr(window, "_learning_dispatch_context", {}) or {}), {}
    )
    if context:
        return (
            str(context.get("source") or "explicit_context"),
            str(context.get("reason")) if context.get("reason") is not None else None,
        )

    frames = _caller_frames(limit=10)
    functions = [str(row.get("function") or "") for row in frames]
    if "_build_learning_center" in functions:
        return "startup_learning_tab_build", "initial_learning_tab_build"
    if "_on_learning_refresh_ready" in functions:
        return "pending_after_ready", "learning_refresh_pending"
    if "_on_learning_refresh_failed" in functions:
        return "pending_after_failure", "learning_refresh_pending"
    if "_drain_coalesced_gui_refresh" in functions:
        return "coalesced_gui_refresh", None
    if args and isinstance(args[0], bool):
        return "learning_refresh_button", "button_clicked"
    return "unknown_caller", None
