"""DVS AI v2.4.3 RC6.8 — Qt Shutdown/Object Lifetime Forensics.

Observation only. This module never calls deleteLater(), sendPostedEvents(),
quit(), wait(), terminate(), processEvents(), or changes QObject ownership.
"""

from __future__ import annotations

import json
import os
import threading
import time
import weakref
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread
from PySide6.QtWidgets import QApplication, QWidget

_RUNTIME = Path("artifacts/runtime")
_TIMELINE = _RUNTIME / "shutdown_phase_timeline.jsonl"
_DESTROY = _RUNTIME / "qobject_shutdown_destroy_trace.jsonl"
_DEFERRED = _RUNTIME / "deferred_delete_trace.jsonl"
_THREADS = _RUNTIME / "managed_qthread_shutdown.jsonl"
_SNAPSHOT = _RUNTIME / "qobject_shutdown_snapshot.json"
_REMAINING = _RUNTIME / "shutdown_remaining_objects.json"

_LOCK = threading.RLock()
_SEQUENCE = 0
_FILTER = None
_TRACKED: dict[int, dict[str, Any]] = {}


def _next_sequence() -> int:
    global _SEQUENCE
    with _LOCK:
        _SEQUENCE += 1
        return _SEQUENCE


def _append(path: Path, event: str, **extra: Any) -> None:
    row = {
        "schema_version": "dvs.runtime.qt_shutdown_forensics.v1",
        "event": str(event),
        "sequence": _next_sequence(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_ns": time.monotonic_ns(),
        "pid": os.getpid(),
        "thread_ident": threading.get_ident(),
        **extra,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n"
        with _LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
    except Exception:
        pass


def _safe_call(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _cpp_address(obj: object | None) -> str | None:
    if obj is None:
        return None
    try:
        import shiboken6
        pointer = shiboken6.getCppPointer(obj)
        return hex(int(pointer[0])) if pointer else None
    except Exception:
        return None


def _valid(obj: object | None) -> bool | None:
    if obj is None:
        return None
    try:
        import shiboken6
        return bool(shiboken6.isValid(obj))
    except Exception:
        return None


def describe_object(obj: object | None, label: str | None = None) -> dict[str, Any]:
    if obj is None:
        return {
            "label": label,
            "python_id": None,
            "cpp_address": None,
            "class_name": None,
            "object_name": None,
            "valid": None,
        }
    parent = _safe_call(lambda: obj.parent(), None)
    thread = _safe_call(lambda: obj.thread(), None)
    row = {
        "label": label,
        "python_id": hex(id(obj)),
        "cpp_address": _cpp_address(obj),
        "class_name": _safe_call(lambda: obj.metaObject().className(), type(obj).__name__),
        "python_class_name": type(obj).__name__,
        "object_name": _safe_call(lambda: obj.objectName(), ""),
        "valid": _valid(obj),
        "parent_python_id": hex(id(parent)) if parent is not None else None,
        "parent_cpp_address": _cpp_address(parent),
        "parent_class_name": _safe_call(
            lambda: parent.metaObject().className() if parent is not None else None,
            None,
        ),
        "thread_python_id": hex(id(thread)) if thread is not None else None,
        "thread_cpp_address": _cpp_address(thread),
        "thread_object_name": _safe_call(
            lambda: thread.objectName() if thread is not None else None,
            None,
        ),
        "is_widget": isinstance(obj, QWidget),
        "is_qthread": isinstance(obj, QThread),
    }
    if isinstance(obj, QThread):
        row.update({
            "is_running": _safe_call(lambda: bool(obj.isRunning()), None),
            "is_finished": _safe_call(lambda: bool(obj.isFinished()), None),
            "interruption_requested": _safe_call(
                lambda: bool(obj.isInterruptionRequested()), None
            ),
        })
    return row


class _DeferredDeleteFilter(QObject):
    def eventFilter(self, watched, event):  # noqa: N802
        try:
            event_type = int(event.type())
        except Exception:
            event_type = None
        if event_type == int(QEvent.Type.DeferredDelete):
            metadata = _TRACKED.get(id(watched), describe_object(watched))
            _append(
                _DEFERRED,
                "deferred_delete_observed",
                event_type=event_type,
                **metadata,
            )
        return False


def _destroyed_callback(metadata: dict[str, Any]):
    def _callback(*_args):
        _append(_DESTROY, "qobject_destroyed", **metadata)
        _TRACKED.pop(int(metadata.get("_key", 0) or 0), None)
    return _callback


def track_object(obj: object | None, label: str) -> bool:
    if obj is None:
        return False
    key = id(obj)
    if key in _TRACKED:
        return True
    metadata = describe_object(obj, label)
    metadata["_key"] = key
    _TRACKED[key] = metadata
    # RC6.10 safety rule: never attach a Python callback to QObject.destroyed
    # and never install a DeferredDelete event filter on runtime objects.
    # Both paths execute while C++ destruction is in progress and can force
    # Shiboken to resolve an already-invalid wrapper.
    _append(
        _TIMELINE,
        "qobject_snapshot_registered",
        observer_mode="snapshot_only",
        **metadata,
    )
    return True


def record_phase(event: str, **extra: Any) -> None:
    _append(
        _TIMELINE,
        event,
        application_closing_down=_safe_call(QCoreApplication.closingDown, None),
        application_starting_up=_safe_call(QCoreApplication.startingUp, None),
        **extra,
    )


def record_thread_operation(event: str, thread: object | None, **extra: Any) -> None:
    _append(_THREADS, event, **describe_object(thread), **extra)


def _collect_objects(app: QApplication | None, window: QObject | None) -> list[QObject]:
    objects: list[QObject] = []
    seen: set[int] = set()

    def add(obj):
        if obj is None or id(obj) in seen:
            return
        seen.add(id(obj))
        objects.append(obj)

    add(app)
    add(window)
    if window is not None:
        for child in _safe_call(lambda: window.findChildren(QObject), []) or []:
            add(child)
    if app is not None:
        for widget in _safe_call(app.allWidgets, []) or []:
            add(widget)
    return objects


def snapshot_shutdown_state(
    reason: str,
    *,
    app: QApplication | None,
    window: QObject | None,
) -> dict[str, Any]:
    objects = _collect_objects(app, window)
    entries = [describe_object(obj) for obj in objects]
    threads = [row for row in entries if row.get("is_qthread")]
    widgets = [row for row in entries if row.get("is_widget")]
    running_threads = [row for row in threads if row.get("is_running")]
    payload = {
        "schema_version": "dvs.runtime.qt_shutdown_snapshot.v1",
        "reason": reason,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_ns": time.monotonic_ns(),
        "pid": os.getpid(),
        "application_closing_down": _safe_call(QCoreApplication.closingDown, None),
        "application_starting_up": _safe_call(QCoreApplication.startingUp, None),
        "total_objects": len(entries),
        "qthreads": len(threads),
        "running_qthreads": len(running_threads),
        "widgets": len(widgets),
        "tracked_objects": len(_TRACKED),
        "entries": entries,
    }
    try:
        _RUNTIME.mkdir(parents=True, exist_ok=True)
        _SNAPSHOT.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        _REMAINING.write_text(
            json.dumps(
                {
                    "schema_version": "dvs.runtime.shutdown_remaining_objects.v1",
                    "reason": reason,
                    "timestamp_utc": payload["timestamp_utc"],
                    "running_threads": running_threads,
                    "tracked_not_destroyed": list(_TRACKED.values()),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass
    record_phase(
        "qobject_shutdown_snapshot",
        reason=reason,
        total_objects=len(entries),
        qthreads=len(threads),
        running_qthreads=len(running_threads),
        widgets=len(widgets),
        tracked_objects=len(_TRACKED),
    )
    return payload


def install_qt_shutdown_forensics(
    app: QApplication,
    window: QObject,
) -> None:
    global _FILTER
    _FILTER = None

    track_object(app, "qapplication")
    track_object(window, "main_window")

    # Track high-value objects only. A complete static census is still written
    # at shutdown, while limiting signal/event-filter observer effect.
    targeted_names = (
        "truth", "scan", "learning", "outcome", "paper", "history",
        "finalization", "qualification", "signal", "runtime", "worker",
    )
    for obj in _collect_objects(app, window):
        name = str(_safe_call(lambda: obj.objectName(), "") or "").lower()
        cls = str(_safe_call(lambda: obj.metaObject().className(), type(obj).__name__) or "").lower()
        if isinstance(obj, QThread) or any(token in name or token in cls for token in targeted_names):
            track_object(obj, f"target:{name or cls}")

    try:
        def _on_about_to_quit():
            record_phase("qt_about_to_quit")
            snapshot_shutdown_state(
                "qt_about_to_quit",
                app=app,
                window=window,
            )
            try:
                from dvs_ai.runtime.shiboken_wrapper_forensics import (
                    record_wrapper_boundary,
                    snapshot_wrappers,
                )
                record_wrapper_boundary(
                    "qt_about_to_quit_mainwindow",
                    window,
                    label="main_window",
                )
                snapshot_wrappers(
                    "qt_about_to_quit",
                    app=app,
                    window=window,
                )
            except Exception:
                pass

        app.aboutToQuit.connect(_on_about_to_quit)
    except Exception as exc:
        record_phase("about_to_quit_connect_failed", error=repr(exc))

    try:
        def _on_last_window_closed():
            record_phase("qt_last_window_closed")
            try:
                from dvs_ai.runtime.shiboken_wrapper_forensics import (
                    record_wrapper_boundary,
                    snapshot_wrappers,
                )
                record_wrapper_boundary(
                    "qt_last_window_closed_mainwindow",
                    window,
                    label="main_window",
                )
                snapshot_wrappers(
                    "qt_last_window_closed",
                    app=app,
                    window=window,
                )
            except Exception:
                pass

        app.lastWindowClosed.connect(_on_last_window_closed)
    except Exception as exc:
        record_phase("last_window_closed_connect_failed", error=repr(exc))

    record_phase(
        "qt_shutdown_forensics_installed",
        observer_mode="snapshot_only_no_destroyed_callbacks",
        tracked_objects=len(_TRACKED),
        **describe_object(window, "main_window"),
    )
