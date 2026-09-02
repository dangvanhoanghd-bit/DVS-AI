"""DVS AI v2.4.3 RC2 — MainWindow Wrapper-State Isolation.

Instrumentation only. This module does not call close(), deleteLater(), quit(),
processEvents(), change QObject parenting, or change ownership. It records the
state of the MainWindow wrapper and observes Close/DeferredDelete events.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QEvent, QTimer, QCoreApplication

_TRACE_SCHEMA = "dvs.runtime.mainwindow_wrapper_trace.v1"
_KEEPALIVE: list[QObject] = []
_ACTIVE_TRACKER = None
_WRITE_LOCK = threading.Lock()


def _safe_call(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _wrapper_state(window: object | None) -> dict[str, Any]:
    state: dict[str, Any] = {
        "python_id": hex(id(window)) if window is not None else None,
        "class_name": None,
        "object_name": None,
        "cpp_address": None,
        "shiboken_valid": None,
        "owned_by_python": "unsupported",
        "created_by_python": "unsupported",
        "wa_delete_on_close": None,
    }
    if window is None:
        return state

    state["class_name"] = _safe_call(
        lambda: window.metaObject().className(), type(window).__name__
    )
    state["object_name"] = _safe_call(lambda: window.objectName(), None)

    try:
        import shiboken6

        pointers = shiboken6.getCppPointer(window)
        if pointers:
            state["cpp_address"] = hex(pointers[0])
        state["shiboken_valid"] = bool(shiboken6.isValid(window))

        owned = getattr(shiboken6, "ownedByPython", None)
        if callable(owned):
            state["owned_by_python"] = bool(owned(window))

        created = getattr(shiboken6, "createdByPython", None)
        if callable(created):
            state["created_by_python"] = bool(created(window))
    except Exception as exc:
        state["shiboken_error"] = repr(exc)

    try:
        from PySide6.QtCore import Qt
        state["wa_delete_on_close"] = bool(
            window.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        )
    except Exception:
        pass

    return state


class _MainWindowEventFilter(QObject):
    """Read-only event observer retained by a module-level strong reference."""

    def __init__(self, *, out_path: Path, build_id: str | None) -> None:
        super().__init__(None)
        self._out_path = out_path
        self._build_id = build_id
        self._sequence = 0

    def write(self, event_name: str, window: object | None, **extra: Any) -> None:
        self._sequence += 1
        payload: dict[str, Any] = {
            "schema_version": _TRACE_SCHEMA,
            "event": event_name,
            "sequence": self._sequence,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "monotonic_ns": time.monotonic_ns(),
            "pid": os.getpid(),
            "thread_ident": threading.get_ident(),
            "build_id": self._build_id,
            **_wrapper_state(window),
            **extra,
        }
        try:
            self._out_path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
            with _WRITE_LOCK:
                with self._out_path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                    handle.flush()
        except Exception:
            # Forensics must never alter application control flow.
            pass

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        try:
            event_type = int(event.type())
            if event.type() == QEvent.Type.Close:
                self.write(
                    "close_event_observed",
                    watched,
                    event_type=event_type,
                    event_accepted=bool(event.isAccepted()),
                )

                # A zero-delay callback executes only after the Close event
                # handler has returned to the event loop. It is observation
                # only and does not accept/ignore/close/quit anything.
                watched_ref = watched

                def _after_close_dispatch() -> None:
                    try:
                        app = QCoreApplication.instance()
                        self.write(
                            "close_event_dispatch_returned",
                            watched_ref,
                            window_visible=bool(watched_ref.isVisible()),
                            window_hidden=bool(watched_ref.isHidden()),
                            app_closing_down=bool(QCoreApplication.closingDown()),
                            app_instance_present=app is not None,
                        )
                    except Exception as exc:
                        self.write(
                            "close_event_dispatch_probe_failed",
                            watched_ref,
                            error=repr(exc),
                        )

                QTimer.singleShot(0, _after_close_dispatch)
            elif event.type() == QEvent.Type.DeferredDelete:
                self.write(
                    "deferred_delete_observed",
                    watched,
                    event_type=event_type,
                    event_accepted=bool(event.isAccepted()),
                )
        except Exception:
            pass
        return False


def install_mainwindow_wrapper_trace(
    window: QObject,
    *,
    out_path: str | Path = "artifacts/runtime/mainwindow_wrapper_trace.jsonl",
    build_id: str | None = None,
) -> _MainWindowEventFilter:
    """Install instrumentation without modifying lifecycle or ownership."""
    global _ACTIVE_TRACKER
    tracker = _MainWindowEventFilter(out_path=Path(out_path), build_id=build_id)
    _ACTIVE_TRACKER = tracker
    _KEEPALIVE.append(tracker)

    state = _wrapper_state(window)
    tracker.write("trace_installed", window, observer_class=type(tracker).__name__)

    try:
        window.installEventFilter(tracker)
        tracker.write("event_filter_installed", window)
    except Exception as exc:
        tracker.write("event_filter_install_failed", window, error=repr(exc))

    # Capture immutable identity now; do not dereference a mid-destruction wrapper.
    destroyed_identity = dict(state)

    def _on_destroyed(*_args: Any) -> None:
        tracker._sequence += 1
        payload = {
            "schema_version": _TRACE_SCHEMA,
            "event": "destroyed_signal",
            "sequence": tracker._sequence,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "monotonic_ns": time.monotonic_ns(),
            "pid": os.getpid(),
            "thread_ident": threading.get_ident(),
            "build_id": build_id,
            **destroyed_identity,
        }
        try:
            tracker._out_path.parent.mkdir(parents=True, exist_ok=True)
            with _WRITE_LOCK:
                with tracker._out_path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
                    )
                    handle.flush()
        except Exception:
            pass

    try:
        window.destroyed.connect(_on_destroyed)
        tracker.write("destroyed_signal_connected", window)
    except Exception as exc:
        tracker.write("destroyed_signal_connect_failed", window, error=repr(exc))

    return tracker


def record_mainwindow_wrapper_state(
    tracker: _MainWindowEventFilter | None,
    event_name: str,
    window: object | None,
    **extra: Any,
) -> None:
    if tracker is None:
        return
    try:
        tracker.write(event_name, window, **extra)
    except Exception:
        pass


def install_application_exit_trace(
    app: QObject,
    tracker: _MainWindowEventFilter | None,
    window: object | None,
) -> None:
    """Observe Qt application exit signals without changing exit policy."""

    if tracker is None:
        return

    try:
        app.aboutToQuit.connect(
            lambda: tracker.write(
                "qt_about_to_quit_signal",
                window,
                app_closing_down=bool(QCoreApplication.closingDown()),
            )
        )
        tracker.write("qt_about_to_quit_connected", window)
    except Exception as exc:
        tracker.write(
            "qt_about_to_quit_connect_failed",
            window,
            error=repr(exc),
        )

    try:
        last_window_closed = getattr(app, "lastWindowClosed", None)
        if last_window_closed is not None:
            last_window_closed.connect(
                lambda: tracker.write(
                    "qt_last_window_closed_signal",
                    window,
                    app_closing_down=bool(QCoreApplication.closingDown()),
                )
            )
            tracker.write("qt_last_window_closed_connected", window)
    except Exception as exc:
        tracker.write(
            "qt_last_window_closed_connect_failed",
            window,
            error=repr(exc),
        )


def _thread_running(window: object, attribute: str) -> bool | None:
    try:
        thread = getattr(window, attribute, None)
        if thread is None:
            return None
        fn = getattr(thread, "isRunning", None)
        return bool(fn()) if callable(fn) else None
    except Exception:
        return None


def _close_policy_state(window: object | None) -> dict[str, Any]:
    if window is None:
        return {}

    state: dict[str, Any] = {}
    for attribute in (
        "is_closing",
        "_shutdown_pre_registry_complete",
        "_learning_refresh_running",
        "_scan_worker_running",
        "_scan_running",
        "_is_scanning",
        "scan_in_progress",
    ):
        try:
            value = getattr(window, attribute, None)
            state[attribute] = (
                value if isinstance(value, (bool, int, float, str)) or value is None
                else repr(value)
            )
        except Exception:
            state[attribute] = "unavailable"

    for attribute in (
        "_qualification_metrics_thread",
        "_universe_thread",
        "_api_health_thread",
        "_learning_thread",
        "_signal_record_thread",
        "_object_census_thread",
        "_auto_paper_worker_thread",
        "finalization_thread",
        "_scan_runtime_thread",
    ):
        state[f"{attribute}_running"] = _thread_running(window, attribute)

    try:
        state["worker_present"] = getattr(window, "worker", None) is not None
    except Exception:
        state["worker_present"] = None

    try:
        status = getattr(window, "status", None)
        state["status_text"] = (
            status.text() if status is not None and hasattr(status, "text") else None
        )
    except Exception:
        state["status_text"] = None

    return state


def record_close_policy_decision(
    window: object | None,
    event_name: str,
    *,
    close_event: object | None = None,
    reason: str | None = None,
    **extra: Any,
) -> None:
    tracker = _ACTIVE_TRACKER
    if tracker is None:
        return

    payload: dict[str, Any] = {
        "reason": reason,
        **_close_policy_state(window),
        **extra,
    }
    if close_event is not None:
        try:
            payload["event_accepted"] = bool(close_event.isAccepted())
        except Exception:
            payload["event_accepted"] = None
        try:
            payload["event_type"] = int(close_event.type())
        except Exception:
            payload["event_type"] = None

    tracker.write(event_name, window, **payload)
