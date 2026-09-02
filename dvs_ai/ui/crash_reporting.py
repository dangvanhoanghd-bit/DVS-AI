from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
import threading
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

_LOCK = RLock()
_LOG_DIR = Path("logs")
_CRASH_LOG = _LOG_DIR / "gui_crash.log"
_FATAL_LOG = _LOG_DIR / "native_fault.log"
_INSTALLED = False


def _append(text: str) -> None:
    with _LOCK:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _CRASH_LOG.open("a", encoding="utf-8") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")


def install_global_exception_reporting() -> None:
    """Capture unhandled Python exceptions and prove installation at runtime."""
    global _INSTALLED
    if _INSTALLED:
        return
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    previous = sys.excepthook

    def hook(exc_type, exc_value, exc_tb):
        stamp = datetime.now(timezone.utc).isoformat()
        rendered = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _append(f"\n[{stamp}] UNHANDLED_PYTHON_EXCEPTION\n{rendered}")
        logging.getLogger(__name__).critical("Unhandled GUI exception", exc_info=(exc_type, exc_value, exc_tb))
        previous(exc_type, exc_value, exc_tb)

    sys.excepthook = hook

    previous_thread_hook = getattr(threading, "excepthook", None)
    def thread_hook(args):
        stamp = datetime.now(timezone.utc).isoformat()
        rendered = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        _append(f"\n[{stamp}] UNHANDLED_THREAD_EXCEPTION\nthread={getattr(args.thread, 'name', '')}\n{rendered}")
        if previous_thread_hook is not None:
            previous_thread_hook(args)
    threading.excepthook = thread_hook

    previous_unraisable = getattr(sys, "unraisablehook", None)
    def unraisable_hook(args):
        stamp = datetime.now(timezone.utc).isoformat()
        rendered = "".join(traceback.format_exception(type(args.exc_value), args.exc_value, args.exc_traceback)) if args.exc_value else str(args.err_msg or "unraisable")
        _append(f"\n[{stamp}] UNRAISABLE_EXCEPTION\nobject={args.object!r}\n{rendered}")
        if previous_unraisable is not None:
            previous_unraisable(args)
    sys.unraisablehook = unraisable_hook
    _INSTALLED = True
    payload = {
        "schema_version": "dvs.runtime.exception_hook.v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_ns": time.monotonic_ns(),
        "event": "global_exception_reporting_installed",
        "pid": os.getpid(),
        "thread": "MainThread" if __import__("threading").current_thread().name == "MainThread" else __import__("threading").current_thread().name,
        "previous_hook": getattr(previous, "__name__", type(previous).__name__),
    }
    try:
        path = Path("artifacts/runtime/exception_hook.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        logging.getLogger(__name__).exception("Failed to persist exception-hook installation evidence")


def log_gui_exception(*, context: str, symbol: str = "", exc: BaseException) -> None:
    stamp = datetime.now(timezone.utc).isoformat()
    rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    _append(
        f"\n[{stamp}] GUI_EVENT_FAILURE\ncontext={context}\nsymbol={symbol}\n{rendered}"
    )
