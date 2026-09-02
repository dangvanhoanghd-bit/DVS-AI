"""DVS AI v2.4.3 RC6.9 — Shiboken Wrapper Lifetime Forensics.

Observation only. This module does not delete, invalidate, transfer ownership,
change QObject parents, process events, or control QThread lifecycle.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import weakref
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread
from PySide6.QtWidgets import QApplication, QWidget

_RUNTIME = Path("artifacts/runtime")
_EVENTS = _RUNTIME / "shiboken_wrapper_lifetime.jsonl"
_SNAPSHOT = _RUNTIME / "shiboken_wrapper_snapshot.json"
_INDEX = _RUNTIME / "shiboken_wrapper_cpp_index.json"
_FINALIZERS = _RUNTIME / "python_wrapper_finalize_trace.jsonl"

_LOCK = threading.RLock()
_SEQUENCE = 0
_TRACKED: dict[int, dict[str, Any]] = {}
_FINALIZER_HANDLES: list[weakref.finalize] = []


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


def _append(path: Path, event: str, **extra: Any) -> None:
    row = {
        "schema_version": "dvs.runtime.shiboken_wrapper_forensics.v1",
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


def wrapper_metadata(obj: object | None, label: str | None = None) -> dict[str, Any]:
    if obj is None:
        return {
            "label": label,
            "python_id": None,
            "cpp_address": None,
            "class_name": None,
            "object_name": None,
            "shiboken_valid": None,
            "created_by_python": None,
            "owned_by_python": None,
            "python_refcount": None,
        }

    try:
        import shiboken6
    except Exception:
        shiboken6 = None

    pointers = _safe_call(
        lambda: shiboken6.getCppPointer(obj) if shiboken6 is not None else (),
        (),
    )
    cpp_address = hex(int(pointers[0])) if pointers else None
    parent = _safe_call(lambda: obj.parent(), None) if isinstance(obj, QObject) else None
    affinity = _safe_call(lambda: obj.thread(), None) if isinstance(obj, QObject) else None

    metadata = {
        "label": label,
        "python_id": hex(id(obj)),
        "cpp_address": cpp_address,
        "cpp_pointers": [hex(int(value)) for value in pointers] if pointers else [],
        "class_name": _safe_call(
            lambda: obj.metaObject().className(),
            type(obj).__name__,
        ),
        "python_class_name": type(obj).__name__,
        "object_name": _safe_call(lambda: obj.objectName(), "")
        if isinstance(obj, QObject)
        else None,
        "shiboken_valid": _safe_call(
            lambda: bool(shiboken6.isValid(obj)) if shiboken6 is not None else None,
            None,
        ),
        "created_by_python": _safe_call(
            lambda: bool(shiboken6.createdByPython(obj))
            if shiboken6 is not None
            else None,
            None,
        ),
        "owned_by_python": _safe_call(
            lambda: bool(shiboken6.ownedByPython(obj))
            if shiboken6 is not None
            else None,
            None,
        ),
        # getrefcount includes the temporary reference passed into this function.
        "python_refcount": _safe_call(lambda: max(0, sys.getrefcount(obj) - 1), None),
        "parent_python_id": hex(id(parent)) if parent is not None else None,
        "parent_cpp_address": _safe_call(
            lambda: hex(int(shiboken6.getCppPointer(parent)[0]))
            if shiboken6 is not None and parent is not None
            else None,
            None,
        ),
        "parent_class_name": _safe_call(
            lambda: parent.metaObject().className() if parent is not None else None,
            None,
        ),
        "affinity_thread_python_id": hex(id(affinity)) if affinity is not None else None,
        "affinity_thread_object_name": _safe_call(
            lambda: affinity.objectName() if affinity is not None else None,
            None,
        ),
        "is_qobject": isinstance(obj, QObject),
        "is_widget": isinstance(obj, QWidget),
        "is_qthread": isinstance(obj, QThread),
    }
    if isinstance(obj, QThread):
        metadata.update({
            "thread_running": _safe_call(lambda: bool(obj.isRunning()), None),
            "thread_finished": _safe_call(lambda: bool(obj.isFinished()), None),
            "thread_interruption_requested": _safe_call(
                lambda: bool(obj.isInterruptionRequested()),
                None,
            ),
        })
    return metadata


def _python_finalize_callback(metadata: dict[str, Any]) -> None:
    _append(_FINALIZERS, "python_wrapper_finalized", **metadata)


def _destroyed_callback(metadata: dict[str, Any]):
    def _callback(*_args):
        current = dict(metadata)
        current["destroyed_signal_observed"] = True
        _append(_EVENTS, "cpp_qobject_destroyed_signal", **current)
    return _callback


def track_wrapper(obj: object | None, label: str) -> bool:
    if obj is None:
        return False
    key = id(obj)
    if key in _TRACKED:
        return True

    metadata = wrapper_metadata(obj, label)
    _TRACKED[key] = metadata
    _append(
        _EVENTS,
        "wrapper_snapshot_registered",
        observer_mode="snapshot_only",
        **metadata,
    )

    # RC6.10 safety rule:
    # - no QObject.destroyed.connect(Python callback)
    # - no weakref.finalize callback
    # The RC6.9 dump proved that Python callback dispatch from QObject::~QObject
    # can enter Shiboken::Object::cppPointers after the C++ pointer table has
    # already been invalidated.
    return True


def collect_target_wrappers(
    app: QApplication | None,
    window: QObject | None,
) -> list[tuple[object, str]]:
    found: list[tuple[object, str]] = []
    seen: set[int] = set()

    def add(obj: object | None, label: str) -> None:
        if obj is None or id(obj) in seen:
            return
        seen.add(id(obj))
        found.append((obj, label))

    add(app, "qapplication")
    add(window, "main_window")

    target_tokens = (
        "main", "truth", "scan", "learning", "outcome", "paper", "history",
        "runtime", "finalization", "worker", "thread", "dashboard",
        "qualification", "signal", "telemetry",
    )

    if window is not None:
        descendants = _safe_call(lambda: window.findChildren(QObject), []) or []
        for obj in descendants:
            name = str(_safe_call(lambda: obj.objectName(), "") or "").lower()
            cls = str(
                _safe_call(lambda: obj.metaObject().className(), type(obj).__name__)
                or ""
            ).lower()
            if isinstance(obj, QThread) or any(
                token in name or token in cls for token in target_tokens
            ):
                add(obj, f"target:{name or cls}")

    if app is not None:
        for widget in _safe_call(app.allWidgets, []) or []:
            name = str(_safe_call(lambda: widget.objectName(), "") or "").lower()
            cls = str(
                _safe_call(
                    lambda: widget.metaObject().className(),
                    type(widget).__name__,
                )
                or ""
            ).lower()
            if any(token in name or token in cls for token in target_tokens):
                add(widget, f"widget:{name or cls}")

    return found


def install_wrapper_forensics(
    app: QApplication,
    window: QObject,
) -> int:
    targets = collect_target_wrappers(app, window)
    for obj, label in targets:
        track_wrapper(obj, label)
    _append(
        _EVENTS,
        "wrapper_forensics_installed",
        observer_mode="snapshot_only_no_destroyed_or_finalize_callbacks",
        tracked_count=len(_TRACKED),
    )
    return len(_TRACKED)


def snapshot_wrappers(
    reason: str,
    *,
    app: QApplication | None,
    window: QObject | None,
) -> dict[str, Any]:
    # Refresh the target set so wrappers created after startup are included.
    for obj, label in collect_target_wrappers(app, window):
        track_wrapper(obj, label)

    entries: list[dict[str, Any]] = []
    cpp_index: dict[str, list[dict[str, Any]]] = {}

    for obj, label in collect_target_wrappers(app, window):
        metadata = wrapper_metadata(obj, label)
        entries.append(metadata)
        cpp_address = metadata.get("cpp_address")
        if cpp_address:
            cpp_index.setdefault(str(cpp_address).lower(), []).append(metadata)

    payload = {
        "schema_version": "dvs.runtime.shiboken_wrapper_snapshot.v1",
        "reason": str(reason),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_ns": time.monotonic_ns(),
        "pid": os.getpid(),
        "entry_count": len(entries),
        "valid_count": sum(row.get("shiboken_valid") is True for row in entries),
        "invalid_count": sum(row.get("shiboken_valid") is False for row in entries),
        "created_by_python_count": sum(
            row.get("created_by_python") is True for row in entries
        ),
        "owned_by_python_count": sum(
            row.get("owned_by_python") is True for row in entries
        ),
        "entries": entries,
    }

    try:
        _RUNTIME.mkdir(parents=True, exist_ok=True)
        _SNAPSHOT.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        _INDEX.write_text(
            json.dumps(
                {
                    "schema_version": "dvs.runtime.shiboken_wrapper_cpp_index.v1",
                    "reason": str(reason),
                    "timestamp_utc": payload["timestamp_utc"],
                    "cpp_index": cpp_index,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass

    _append(
        _EVENTS,
        "wrapper_snapshot_written",
        reason=str(reason),
        entry_count=payload["entry_count"],
        valid_count=payload["valid_count"],
        invalid_count=payload["invalid_count"],
        created_by_python_count=payload["created_by_python_count"],
        owned_by_python_count=payload["owned_by_python_count"],
    )
    return payload


def record_wrapper_boundary(
    event: str,
    obj: object | None,
    *,
    label: str | None = None,
    **extra: Any,
) -> None:
    _append(
        _EVENTS,
        event,
        **wrapper_metadata(obj, label),
        **extra,
    )
