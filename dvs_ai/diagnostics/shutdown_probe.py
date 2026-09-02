from __future__ import annotations

import atexit
import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication

try:
    import shiboken6
except Exception:  # optional diagnostic dependency supplied with PySide6
    shiboken6 = None


class _QuitEventFilter(QObject):
    """Observe Qt quit/close events without altering their delivery."""

    def __init__(self, probe: "ShutdownProbe") -> None:
        super().__init__()
        self._probe = probe

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        try:
            event_type = event.type()
            if event_type in (QEvent.Type.Quit, QEvent.Type.Close, QEvent.Type.DeferredDelete):
                self._probe.record(
                    "qt_event",
                    event_type=int(event_type),
                    watched_class=type(watched).__name__,
                    watched_object_name=getattr(watched, "objectName", lambda: "")(),
                )
        except Exception as exc:
            self._probe.record("probe_internal_error", operation="eventFilter", error=repr(exc))
        return False


class ShutdownProbe:
    """Low-impact lifecycle recorder for shutdown-origin investigations.

    The probe is intentionally observe-only: it does not stop threads, cancel
    timers, alter Qt event delivery, or change application exit codes.
    """

    def __init__(self, root: Path | str = Path("artifacts/runtime")) -> None:
        self.root = Path(root)
        self.heavy_forensics_enabled = str(
            os.environ.get("DVS_FORENSIC_MODE", "0")
        ).strip().lower() in {"1", "true", "yes", "on"}
        self.root.mkdir(parents=True, exist_ok=True)
        self.timeline_path = self.root / "shutdown_probe.jsonl"
        self.thread_snapshot_path = self.root / "shutdown_thread_snapshots.jsonl"
        self.thread_delta_path = self.root / "thread_delta_forensics.jsonl"
        self.native_object_path = self.root / "native_object_destruction.jsonl"
        self.thread_registry_path = self.root / "dummy_thread_registry_forensics.jsonl"
        self.qt_thread_mapping_path = self.root / "qt_thread_mapping_forensics.jsonl"
        self.qobject_correlation_path = self.root / "tracked_qobject_correlation.jsonl"
        self.qobject_summary_path = self.root / "tracked_qobject_correlation_summary.json"
        self.application_census_path = self.root / "application_qobject_census.jsonl"
        self.qt_messages_path = self.root / "shutdown_qt_messages.log"
        self.unhandled_path = self.root / "shutdown_unhandled_exception.log"
        self._lock = threading.RLock()
        self._installed = False
        self._app: Optional[QCoreApplication] = None
        self._event_filter: Optional[_QuitEventFilter] = None
        self._previous_sys_exit: Optional[Callable[..., Any]] = None
        self._previous_os_exit: Optional[Callable[..., Any]] = None
        self._previous_sys_hook: Optional[Callable[..., Any]] = None
        self._previous_thread_hook: Optional[Callable[..., Any]] = None
        self._previous_qt_handler: Any = None
        self._started_monotonic = time.monotonic()
        self._previous_thread_snapshot: dict[tuple[Any, Any], dict[str, Any]] = {}
        self._thread_first_seen: dict[tuple[Any, Any], str] = {}
        self._tracked_objects: dict[str, dict[str, Any]] = {}
        self._thread_registry_previous: dict[tuple[Any, Any], dict[str, Any]] = {}
        self._qt_thread_mappings: dict[tuple[Any, Any], dict[str, Any]] = {}
        self._tracked_relations: list[dict[str, str]] = []
        self._destroy_sequence = 0
        self._last_destroyed: list[dict[str, Any]] = []

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _stack(limit: int = 32) -> list[str]:
        return traceback.format_stack(limit=limit)[:-1]

    @staticmethod
    def _thread_payload() -> dict[str, Any]:
        current = threading.current_thread()
        return {
            "thread_name": current.name,
            "thread_ident": current.ident,
            "thread_native_id": getattr(current, "native_id", None),
            "thread_daemon": current.daemon,
            "is_main_thread": current is threading.main_thread(),
        }

    def record(self, event: str, **fields: Any) -> None:
        payload: dict[str, Any] = {
            "ts_utc": self._utc_now(),
            "monotonic_s": round(time.monotonic() - self._started_monotonic, 6),
            "pid": os.getpid(),
            "event": event,
            **self._thread_payload(),
            **fields,
        }
        # RC6.17 (causal fix): RC6.16-r1's independent GUI hang watchdog
        # directly caught the GUI thread's Python stack inside this
        # method's synchronous open/write/flush (via snapshot_threads()),
        # observed_lag_ms=8360 -- record() is called from many sites
        # throughout normal runtime, not only at shutdown, despite the
        # class's name. Enqueue instead of writing inline; a dedicated
        # background thread performs the actual disk I/O. Output format
        # (path, JSON encoding, one line per record) is unchanged.
        try:
            from dvs_ai.runtime.async_jsonl_writer import enqueue_jsonl_write
            enqueue_jsonl_write(self.timeline_path, payload)
        except Exception:
            # A diagnostic probe must never change application behavior.
            pass

    @staticmethod
    def _thread_key(item: dict[str, Any]) -> tuple[Any, Any]:
        # ident is the primary stable key for a live Python thread. native_id is
        # included to protect against ident reuse across rapid teardown/startup.
        return (item.get("ident"), item.get("native_id"))

    @staticmethod
    def _registry_thread_payload(registry_name: str, registry_key: Any, thread: Any) -> dict[str, Any]:
        try:
            ident = getattr(thread, "ident", None)
        except Exception:
            ident = None
        try:
            native_id = getattr(thread, "native_id", None)
        except Exception:
            native_id = None
        try:
            name = getattr(thread, "name", "")
        except Exception:
            name = ""
        try:
            daemon = bool(getattr(thread, "daemon", False))
        except Exception:
            daemon = None
        try:
            alive = bool(thread.is_alive())
        except Exception:
            alive = None
        cls_name = type(thread).__name__
        return {
            "registry": registry_name,
            "registry_key": repr(registry_key),
            "python_object_id": hex(id(thread)),
            "ident": ident,
            "native_id": native_id,
            "name": name,
            "thread_class": cls_name,
            "daemon": daemon,
            "is_alive": alive,
            "is_dummy": cls_name == "_DummyThread",
        }

    def snapshot_thread_registries(self, reason: str) -> None:
        """Observe CPython thread registries without mutating them.

        Private registries are used here strictly for forensic observation. No
        entry is removed, renamed, joined, or otherwise altered.
        """
        try:
            rows: list[dict[str, Any]] = []
            active = getattr(threading, "_active", {})
            limbo = getattr(threading, "_limbo", {})
            dangling = getattr(threading, "_dangling", ())
            active_lock = getattr(threading, "_active_limbo_lock", None)
            if active_lock is None:
                snapshots = (list(active.items()), list(limbo.items()), list(dangling))
            else:
                with active_lock:
                    snapshots = (list(active.items()), list(limbo.items()), list(dangling))
            for key, thread in snapshots[0]:
                rows.append(self._registry_thread_payload("_active", key, thread))
            for key, thread in snapshots[1]:
                rows.append(self._registry_thread_payload("_limbo", key, thread))
            for thread in snapshots[2]:
                rows.append(self._registry_thread_payload("_dangling", None, thread))

            current: dict[tuple[Any, Any], dict[str, Any]] = {}
            for row in rows:
                if row["registry"] == "_active":
                    current[(row.get("ident"), row.get("native_id"))] = row
            previous = self._thread_registry_previous
            added = current.keys() - previous.keys()
            removed = previous.keys() - current.keys()
            persisting = current.keys() & previous.keys()
            payload = {
                "ts_utc": self._utc_now(),
                "monotonic_s": round(time.monotonic() - self._started_monotonic, 6),
                "pid": os.getpid(),
                "reason": reason,
                "active_count": len(snapshots[0]),
                "limbo_count": len(snapshots[1]),
                "dangling_count": len(snapshots[2]),
                "dummy_active_count": sum(1 for r in rows if r["registry"] == "_active" and r["is_dummy"]),
                "rows": rows,
                "active_added": [current[k] for k in sorted(added, key=str)],
                "active_removed": [previous[k] for k in sorted(removed, key=str)],
                "active_persisting": [current[k] for k in sorted(persisting, key=str)],
            }
            with self._lock:
                with self.thread_registry_path.open("a", encoding="utf-8", buffering=1) as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
                    handle.flush()
            self._thread_registry_previous = current
            self.record(
                "thread_registry_snapshot",
                reason=reason,
                active_count=payload["active_count"],
                dummy_active_count=payload["dummy_active_count"],
                limbo_count=payload["limbo_count"],
                dangling_count=payload["dangling_count"],
            )
        except Exception as exc:
            self.record("probe_internal_error", operation="snapshot_thread_registries", error=repr(exc))

    def record_current_thread_mapping(self, pipeline: str, event: str, **fields: Any) -> None:
        if not self.heavy_forensics_enabled:
            return
        """Map the current Python thread wrapper to the current Qt/native thread.

        Capture happens at callback entry, while both wrappers are known-live.
        This method never mutates CPython registries or QObject ownership.
        """
        try:
            py_thread = threading.current_thread()
            qt_thread = QThread.currentThread()
            py_ident = py_thread.ident
            py_native_id = getattr(py_thread, "native_id", None)
            qt_name = ""
            try:
                qt_name = qt_thread.objectName()
            except Exception:
                pass
            payload = {
                "ts_utc": self._utc_now(),
                "monotonic_s": round(time.monotonic() - self._started_monotonic, 6),
                "pid": os.getpid(),
                "pipeline": str(pipeline),
                "event": str(event),
                "python_thread_ident": py_ident,
                "python_native_id": py_native_id,
                "python_thread_name": py_thread.name,
                "python_thread_class": type(py_thread).__name__,
                "python_thread_object_id": hex(id(py_thread)),
                "is_dummy": type(py_thread).__name__ == "_DummyThread",
                "qt_current_thread_python_id": hex(id(qt_thread)),
                "qt_current_thread_cpp_pointer": self._safe_cpp_pointer(qt_thread),
                "qt_current_thread_name": qt_name,
                "qt_wrapper_valid": self._safe_is_valid(qt_thread),
                **fields,
            }
            # Match the current Qt C++ pointer against tracked QThread metadata.
            matches: list[dict[str, Any]] = []
            cpp_pointer = payload["qt_current_thread_cpp_pointer"]
            if cpp_pointer:
                for tracked_name, entry in list(self._tracked_objects.items()):
                    metadata = entry.get("metadata", {})
                    if metadata.get("object_class") in {"QThread", "WorkerThread"} and metadata.get("cpp_pointer") == cpp_pointer:
                        matches.append({"tracked_name": tracked_name, **metadata})
            payload["tracked_qthread_matches"] = matches
            linked_objects: list[dict[str, Any]] = []
            matched_names = {m.get("tracked_name") for m in matches}
            for relation in self._tracked_relations:
                if relation.get("qthread_name") in matched_names:
                    target = self._tracked_objects.get(relation.get("object_name", ""), {})
                    if target:
                        linked_objects.append({"relation": relation, "metadata": target.get("metadata", {})})
            payload["linked_tracked_objects"] = linked_objects
            payload["python_registry_matches"] = self._registry_rows_for_mapping(py_ident, py_native_id)
            key = (py_ident, py_native_id)
            self._qt_thread_mappings[key] = payload
            self._write_correlation("callback_thread_qobject_mapping", mapping=payload)
            # RC6.18: the independent GUI hang watchdog caught this
            # residual synchronous open/write/flush path on the GUI thread.
            # Preserve the exact JSONL path/schema while delegating disk I/O
            # to the shared bounded background writer.
            try:
                from dvs_ai.runtime.async_jsonl_writer import enqueue_jsonl_write
                enqueue_jsonl_write(self.qt_thread_mapping_path, payload)
            except Exception:
                # Diagnostic telemetry must never alter application behavior.
                pass
        except Exception as exc:
            self.record("probe_internal_error", operation="record_current_thread_mapping", error=repr(exc))

    def snapshot_threads(self, reason: str) -> None:
        if not self.heavy_forensics_enabled:
            return
        try:
            frames = sys._current_frames()
            now = self._utc_now()
            threads: list[dict[str, Any]] = []
            current_map: dict[tuple[Any, Any], dict[str, Any]] = {}
            for thread in threading.enumerate():
                frame = frames.get(thread.ident) if thread.ident is not None else None
                item = {
                    "name": thread.name,
                    "ident": thread.ident,
                    "native_id": getattr(thread, "native_id", None),
                    "daemon": thread.daemon,
                    "alive": thread.is_alive(),
                    "is_main": thread is threading.main_thread(),
                    "python_thread_class": type(thread).__name__,
                    "stack": traceback.format_stack(frame, limit=48) if frame is not None else [],
                }
                key = self._thread_key(item)
                first_seen = self._thread_first_seen.setdefault(key, now)
                item["first_seen_timestamp"] = first_seen
                item["last_seen_timestamp"] = now
                threads.append(item)
                current_map[key] = item

            previous = self._previous_thread_snapshot
            added_keys = current_map.keys() - previous.keys()
            removed_keys = previous.keys() - current_map.keys()
            persisting_keys = current_map.keys() & previous.keys()
            delta = {
                "ts_utc": now,
                "monotonic_s": round(time.monotonic() - self._started_monotonic, 6),
                "pid": os.getpid(),
                "reason": reason,
                "previous_count": len(previous),
                "current_count": len(current_map),
                "threads_added": [current_map[k] for k in sorted(added_keys, key=str)],
                "threads_removed": [previous[k] for k in sorted(removed_keys, key=str)],
                "threads_persisting": [current_map[k] for k in sorted(persisting_keys, key=str)],
            }
            payload = {
                "ts_utc": now,
                "monotonic_s": delta["monotonic_s"],
                "pid": os.getpid(),
                "reason": reason,
                "active_count": threading.active_count(),
                "threads": threads,
            }
            with self._lock:
                with self.thread_snapshot_path.open("a", encoding="utf-8", buffering=1) as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
                    handle.flush()
                with self.thread_delta_path.open("a", encoding="utf-8", buffering=1) as handle:
                    handle.write(json.dumps(delta, ensure_ascii=False, default=str) + "\n")
                    handle.flush()
            self._previous_thread_snapshot = current_map
            self.snapshot_thread_registries(reason)
            self.record(
                "thread_snapshot",
                reason=reason,
                active_count=len(threads),
                previous_count=len(previous),
                added_count=len(added_keys),
                removed_count=len(removed_keys),
            )
        except Exception as exc:
            self.record("probe_internal_error", operation="snapshot_threads", error=repr(exc))

    def _native_write(self, event: str, metadata: dict[str, Any], **fields: Any) -> None:
        payload = {
            "ts_utc": self._utc_now(),
            "monotonic_s": round(time.monotonic() - self._started_monotonic, 6),
            "pid": os.getpid(),
            "event": event,
            **metadata,
            **fields,
        }
        try:
            with self._lock:
                with self.native_object_path.open("a", encoding="utf-8", buffering=1) as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
                    handle.flush()
        except Exception:
            pass

    @staticmethod
    def _safe_is_valid(obj: QObject) -> Optional[bool]:
        if shiboken6 is None:
            return None
        try:
            return bool(shiboken6.isValid(obj))
        except Exception:
            return None

    @staticmethod
    def _safe_cpp_pointer(obj: QObject) -> Optional[str]:
        if shiboken6 is None:
            return None
        try:
            pointers = shiboken6.getCppPointer(obj)
            if pointers:
                return hex(int(pointers[0]))
        except Exception:
            return None
        return None

    @staticmethod
    def _tracked_id(name: str, python_object_id: str, cpp_pointer: Optional[str]) -> str:
        raw = f"{name}|{python_object_id}|{cpp_pointer or 'none'}".encode("utf-8")
        return "tq-" + __import__("hashlib").sha256(raw).hexdigest()[:16]

    def register_relation(self, qthread_name: str, object_name: str, relation: str = "owns_execution") -> None:
        """Register a static relation between already tracked objects.

        This is forensic metadata only; it does not alter QObject ownership,
        thread affinity, signals, or shutdown ordering.
        """
        row = {"qthread_name": str(qthread_name), "object_name": str(object_name), "relation": str(relation)}
        if row not in self._tracked_relations:
            self._tracked_relations.append(row)
        self._write_correlation("tracked_relation_registered", relation=row)

    def _write_correlation(self, event: str, **fields: Any) -> None:
        if not self.heavy_forensics_enabled:
            return
        payload = {
            "ts_utc": self._utc_now(),
            "monotonic_s": round(time.monotonic() - self._started_monotonic, 6),
            "pid": os.getpid(),
            "event": event,
            **fields,
        }
        # RC6.17 (causal fix): same reasoning as record() above -- moved
        # off a synchronous open/write/flush sequence onto the shared
        # async writer thread. Output format (path, JSON encoding, one
        # line per record) is unchanged.
        try:
            from dvs_ai.runtime.async_jsonl_writer import enqueue_jsonl_write
            enqueue_jsonl_write(self.qobject_correlation_path, payload)
        except Exception:
            pass

    def _registry_rows_for_mapping(self, py_ident: Any, py_native_id: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            active = getattr(threading, "_active", {})
            lock = getattr(threading, "_active_limbo_lock", None)
            items = list(active.items()) if lock is None else None
            if lock is not None:
                with lock:
                    items = list(active.items())
            for key, thread in items or []:
                row = self._registry_thread_payload("_active", key, thread)
                if row.get("ident") == py_ident and row.get("native_id") == py_native_id:
                    rows.append(row)
        except Exception:
            pass
        return rows

    def _write_final_correlation_summary(self, reason: str) -> None:
        tracked = []
        for name, entry in self._tracked_objects.items():
            meta = dict(entry.get("metadata", {}))
            meta["wrapper_valid"] = self._safe_is_valid(entry.get("object")) if entry.get("object") is not None else False
            meta["destroyed_observed"] = bool(entry.get("destroyed_observed", False))
            tracked.append(meta)
        summary = {
            "schema_version": "dvs.runtime.tracked_qobject_correlation.v1",
            "ts_utc": self._utc_now(),
            "pid": os.getpid(),
            "reason": reason,
            "tracked_objects": tracked,
            "relations": list(self._tracked_relations),
            "last_destroyed": list(self._last_destroyed[-20:]),
            "thread_mappings": list(self._qt_thread_mappings.values()),
        }
        try:
            self.qobject_summary_path.write_text(json.dumps(summary, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
        except Exception:
            pass

    def snapshot_tracked_objects(self, reason: str) -> None:
        if not self.heavy_forensics_enabled:
            return
        # isValid is the only operation performed on live wrappers here. All
        # descriptive metadata was captured at registration time and is never
        # dereferenced after QObject.destroyed.
        for name, entry in list(self._tracked_objects.items()):
            obj = entry.get("object")
            metadata = entry["metadata"]
            valid = self._safe_is_valid(obj) if obj is not None else False
            self._native_write("tracked_object_snapshot", metadata, reason=reason, wrapper_valid=valid)
            self._write_correlation("tracked_object_snapshot", metadata=metadata, reason=reason, wrapper_valid=valid, destroyed_observed=bool(entry.get("destroyed_observed", False)))

    def _append_text(self, path: Path, text: str) -> None:
        try:
            with self._lock:
                self.root.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8", buffering=1) as handle:
                    handle.write(text)
                    if not text.endswith("\n"):
                        handle.write("\n")
                    handle.flush()
        except Exception:
            pass

    def install_pre_qt_hooks(self) -> None:
        if self._installed:
            return
        self._installed = True
        self.record("probe_install_enter", python=sys.version, executable=sys.executable, argv=sys.argv)

        self._previous_sys_exit = sys.exit
        self._previous_os_exit = os._exit
        self._previous_sys_hook = sys.excepthook
        self._previous_thread_hook = getattr(threading, "excepthook", None)

        def traced_sys_exit(code: Any = 0) -> Any:
            self.record("sys_exit_called", code=code, stack=self._stack())
            self.snapshot_threads("sys_exit_called")
            assert self._previous_sys_exit is not None
            return self._previous_sys_exit(code)

        def traced_os_exit(code: int) -> Any:
            self.record("os_exit_called", code=code, stack=self._stack())
            self.snapshot_threads("os_exit_called")
            assert self._previous_os_exit is not None
            return self._previous_os_exit(code)

        def sys_hook(exc_type: type[BaseException], exc_value: BaseException, exc_tb: Any) -> None:
            rendered = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            self.record("sys_excepthook", exc_type=exc_type.__name__, exc_value=repr(exc_value))
            self._append_text(self.unhandled_path, f"[{self._utc_now()}] SYS_EXCEPTHOOK\n{rendered}\n")
            self.snapshot_threads("sys_excepthook")
            if self._previous_sys_hook is not None:
                self._previous_sys_hook(exc_type, exc_value, exc_tb)

        def thread_hook(args: Any) -> None:
            rendered = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
            self.record(
                "threading_excepthook",
                target_thread=getattr(args.thread, "name", ""),
                exc_type=getattr(args.exc_type, "__name__", str(args.exc_type)),
                exc_value=repr(args.exc_value),
            )
            self._append_text(self.unhandled_path, f"[{self._utc_now()}] THREADING_EXCEPTHOOK\n{rendered}\n")
            self.snapshot_threads("threading_excepthook")
            if self._previous_thread_hook is not None:
                self._previous_thread_hook(args)

        def qt_handler(mode: QtMsgType, context: Any, message: str) -> None:
            context_payload = {
                "file": getattr(context, "file", None),
                "line": getattr(context, "line", None),
                "function": getattr(context, "function", None),
                "category": getattr(context, "category", None),
            }
            self.record("qt_message", mode=int(mode), message=message, context=context_payload)
            self._append_text(
                self.qt_messages_path,
                f"[{self._utc_now()}] mode={int(mode)} context={context_payload} message={message}\n",
            )
            if self._previous_qt_handler is not None:
                try:
                    self._previous_qt_handler(mode, context, message)
                except Exception:
                    pass

        sys.exit = traced_sys_exit
        os._exit = traced_os_exit
        sys.excepthook = sys_hook
        if hasattr(threading, "excepthook"):
            threading.excepthook = thread_hook
        try:
            self._previous_qt_handler = qInstallMessageHandler(qt_handler)
        except Exception as exc:
            self.record("probe_internal_error", operation="qInstallMessageHandler", error=repr(exc))

        atexit.register(self._on_atexit)
        self.record("probe_install_exit")

    def attach_application(self, app: QCoreApplication) -> None:
        self._app = app
        self.record(
            "qapplication_attached",
            qt_thread_is_current=(QThread.currentThread() == app.thread()),
            quit_on_last_window_closed=bool(getattr(app, "quitOnLastWindowClosed", lambda: False)()),
        )
        try:
            app.aboutToQuit.connect(self._on_about_to_quit)
        except Exception as exc:
            self.record("probe_internal_error", operation="aboutToQuit.connect", error=repr(exc))
        try:
            last_window_closed = getattr(app, "lastWindowClosed", None)
            if last_window_closed is not None:
                last_window_closed.connect(self._on_last_window_closed)
        except Exception as exc:
            self.record("probe_internal_error", operation="lastWindowClosed.connect", error=repr(exc))
        try:
            self._event_filter = _QuitEventFilter(self)
            app.installEventFilter(self._event_filter)
            self.record("qt_event_filter_installed")
        except Exception as exc:
            self.record("probe_internal_error", operation="installEventFilter", error=repr(exc))

    def register_object(self, name: str, obj: QObject) -> None:
        # Capture every descriptive field while the wrapper is known-valid. The
        # destroyed callback closes over this immutable metadata and never
        # dereferences the QObject after C++ destruction.
        object_name = ""
        parent_class = None
        parent_id = None
        affinity_name = None
        affinity_id = None
        affinity_matches_current = None
        try:
            getter = getattr(obj, "objectName", None)
            if callable(getter):
                object_name = getter()
        except Exception:
            pass
        try:
            parent = obj.parent()
            if parent is not None:
                parent_class = type(parent).__name__
                parent_id = hex(id(parent))
        except Exception:
            pass
        try:
            thread_getter = getattr(obj, "thread", None)
            qt_thread = thread_getter() if callable(thread_getter) else QObject.thread(obj)
            if qt_thread is not None:
                affinity_name = qt_thread.objectName()
                affinity_id = hex(id(qt_thread))
                affinity_matches_current = qt_thread == QThread.currentThread()
        except Exception:
            pass

        python_object_id = hex(id(obj))
        cpp_pointer = self._safe_cpp_pointer(obj)
        tracked_object_id = self._tracked_id(name, python_object_id, cpp_pointer)
        metadata = {
            "name": name,
            "tracked_object_id": tracked_object_id,
            "object_class": type(obj).__name__,
            "object_name": object_name,
            "python_object_id": python_object_id,
            "cpp_pointer": cpp_pointer,
            "parent_class": parent_class,
            "parent_id": parent_id,
            "thread_affinity_name": affinity_name,
            "thread_affinity_id": affinity_id,
            "creation_phase": "registration",
        }
        self._tracked_objects[name] = {"object": obj, "metadata": metadata, "destroyed_observed": False}
        valid = self._safe_is_valid(obj)
        self.record("qobject_registered", **metadata, wrapper_valid=valid, qt_thread_matches_current=affinity_matches_current)
        self._native_write("tracking_registered", metadata, wrapper_valid=valid)
        self._write_correlation("tracked_object_registered", metadata=metadata, wrapper_valid=valid)

        if isinstance(obj, QThread):
            try:
                obj.finished.connect(lambda n=name, m=metadata: (self._native_write("thread_finished", m, name=n), self._write_correlation("qthread_finished", metadata=m)))
            except Exception as exc:
                self.record("probe_internal_error", operation="thread.finished.connect", name=name, error=repr(exc))

        def _destroyed(*_args: Any, n: str = name, m: dict[str, Any] = metadata) -> None:
            # Do not touch obj here. The C++ instance may already be invalid.
            self._destroy_sequence += 1
            destroyed_row = {
                "sequence": self._destroy_sequence,
                "ts_utc": self._utc_now(),
                "tracked_object_id": m.get("tracked_object_id"),
                "name": n,
                "object_class": m.get("object_class"),
                "thread_registry_snapshot": self._registry_rows_for_mapping(threading.current_thread().ident, getattr(threading.current_thread(), "native_id", None)),
            }
            self._native_write("destroyed_signal_entered", m, name=n, wrapper_valid_at_destroy=False, destroy_sequence=self._destroy_sequence)
            self.record("qobject_destroyed", name=n, class_name=m["object_class"], python_object_id=m["python_object_id"], tracked_object_id=m.get("tracked_object_id"), destroy_sequence=self._destroy_sequence)
            self._write_correlation("tracked_object_destroyed", metadata=m, destroy_sequence=self._destroy_sequence, callback_thread=destroyed_row["thread_registry_snapshot"])
            self._last_destroyed.append(destroyed_row)
            self._native_write("destroyed_signal_completed", m, name=n, destroy_sequence=self._destroy_sequence)
            tracked = self._tracked_objects.get(n)
            if tracked is not None:
                tracked["object"] = None
                tracked["destroyed_observed"] = True

        try:
            obj.destroyed.connect(_destroyed)
        except Exception as exc:
            self.record("probe_internal_error", operation="destroyed.connect", name=name, error=repr(exc))


    def snapshot_application_qobjects(self, reason: str) -> None:
        if not self.heavy_forensics_enabled:
            return
        """Capture a bounded, read-only census of application-level Qt objects.

        Only live wrappers are dereferenced. Metadata is captured immediately
        and no references are retained, so this census cannot extend QObject
        lifetime or alter ownership.
        """
        try:
            app = QCoreApplication.instance()
            if app is None:
                return
            candidates: list[tuple[str, QObject]] = [("qapplication", app)]
            try:
                candidates.extend(("app_child", obj) for obj in app.children())
            except Exception:
                pass
            if isinstance(app, QApplication):
                try:
                    candidates.extend(("top_level_widget", obj) for obj in app.topLevelWidgets())
                except Exception:
                    pass
                try:
                    candidates.extend(("all_widget", obj) for obj in app.allWidgets())
                except Exception:
                    pass
            seen: set[int] = set()
            rows: list[dict[str, Any]] = []
            for source, obj in candidates:
                if obj is None or id(obj) in seen:
                    continue
                seen.add(id(obj))
                valid = self._safe_is_valid(obj)
                row: dict[str, Any] = {
                    "source": source,
                    "python_object_id": hex(id(obj)),
                    "object_class": type(obj).__name__,
                    "wrapper_valid": valid,
                    "cpp_pointer": self._safe_cpp_pointer(obj) if valid else None,
                }
                if valid:
                    try:
                        row["object_name"] = obj.objectName()
                    except Exception:
                        row["object_name"] = ""
                    try:
                        parent = obj.parent()
                        row["parent_class"] = type(parent).__name__ if parent is not None else None
                        row["parent_id"] = hex(id(parent)) if parent is not None else None
                    except Exception:
                        row["parent_class"] = None
                        row["parent_id"] = None
                    try:
                        affinity = obj.thread()
                        row["thread_affinity_name"] = affinity.objectName() if affinity is not None else None
                        row["thread_affinity_id"] = hex(id(affinity)) if affinity is not None else None
                    except Exception:
                        row["thread_affinity_name"] = None
                        row["thread_affinity_id"] = None
                rows.append(row)
                if len(rows) >= 5000:
                    break
            payload = {
                "schema": "dvs.runtime.application_qobject_census.v1",
                "ts_utc": self._utc_now(),
                "monotonic_s": round(time.monotonic() - self._started_monotonic, 6),
                "pid": os.getpid(),
                "reason": reason,
                "count": len(rows),
                "valid_count": sum(1 for row in rows if row.get("wrapper_valid")),
                "class_counts": {},
                "rows": rows,
            }
            for row in rows:
                cls = row.get("object_class", "UNKNOWN")
                payload["class_counts"][cls] = payload["class_counts"].get(cls, 0) + 1
            with self._lock:
                with self.application_census_path.open("a", encoding="utf-8", buffering=1) as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
                    handle.flush()
            self.record("application_qobject_census", reason=reason, count=payload["count"], valid_count=payload["valid_count"])
        except Exception as exc:
            self.record("probe_internal_error", operation="snapshot_application_qobjects", error=repr(exc))

    def mark(self, event: str, **fields: Any) -> None:
        self.record(event, **fields)

    def _on_last_window_closed(self) -> None:
        self.record("qt_last_window_closed", stack=self._stack())
        self.snapshot_threads("qt_last_window_closed")
        self.snapshot_tracked_objects("qt_last_window_closed")
        self.snapshot_application_qobjects("qt_last_window_closed")

    def _on_about_to_quit(self) -> None:
        self.record("qt_about_to_quit", stack=self._stack())
        self.snapshot_threads("qt_about_to_quit")
        self.snapshot_tracked_objects("qt_about_to_quit")
        self.snapshot_application_qobjects("qt_about_to_quit")

    def _on_atexit(self) -> None:
        self.record("python_atexit_enter")
        self.snapshot_threads("python_atexit_enter")
        self.snapshot_tracked_objects("python_atexit_enter")
        self.snapshot_application_qobjects("python_atexit_enter")
        self._write_final_correlation_summary("python_atexit_enter")
        self.record("python_atexit_exit")
        # RC6.17: record()/_write_correlation() above now enqueue rather
        # than write inline. Best-effort, bounded wait for the async
        # writer to drain before the process actually exits, so this
        # final shutdown evidence has a chance to reach disk.
        try:
            from dvs_ai.runtime.async_jsonl_writer import flush_and_wait
            flush_and_wait(timeout_s=5.0)
        except Exception:
            pass


_GLOBAL_PROBE: Optional[ShutdownProbe] = None


def install_shutdown_probe(root: Path | str = Path("artifacts/runtime")) -> ShutdownProbe:
    global _GLOBAL_PROBE
    if _GLOBAL_PROBE is None:
        _GLOBAL_PROBE = ShutdownProbe(root)
        _GLOBAL_PROBE.install_pre_qt_hooks()
    return _GLOBAL_PROBE


def get_shutdown_probe() -> Optional[ShutdownProbe]:
    return _GLOBAL_PROBE
