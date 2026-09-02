"""DVS AI v2.4.3 RC6.15 — Independent GUI Hang Watchdog.

Measurement only. This module never calls processEvents(), never touches
Qt objects directly, never terminates or restarts anything, and never
invokes an external debugger. It runs a plain Python daemon thread,
separate from the GUI thread, specifically so it keeps working even if
the GUI thread itself has stopped responding entirely -- the exact
scenario RC6.15 exists to observe.

Known limitation (by design, not a bug): sys._current_frames() only
shows the most recent *Python* frame for each thread. If the GUI thread
is blocked inside native Qt/GDI/SQLite work, the captured stack will
only show the Python call site that led into that native call, not what
is happening inside it. Getting a real native stack requires an external
tool (WinDbg attach, ProcDump) run from OUTSIDE this process. This
module deliberately does not attempt that automatically -- invoking a
debugger against a process that may already be in a fragile state could
make things worse. It only writes a marker (gui_hang_threshold_crossed)
with enough context (PID, thread id, timestamp, Python stacks) for a
human to attach an external tool afterwards if the hang is still active.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_PATH = Path("artifacts/runtime/gui_hang_watchdog.jsonl")
_LOCK = threading.Lock()
_SEQUENCE = 0

_GUI_HEARTBEAT_LOCK = threading.Lock()
_GUI_HEARTBEAT: dict = {
    "last_tick_monotonic_ns": None,
    "tick_sequence": 0,
    "last_event_name": None,
}

# Escalating thresholds, in milliseconds. Only the highest threshold not
# yet reported for the current hang episode triggers a new record, so a
# single ongoing hang produces one record per threshold crossed (4 max),
# not one record per poll.
_THRESHOLDS_MS = (2000.0, 5000.0, 10000.0, 20000.0)

_WATCHDOG_LOCK = threading.Lock()
_WATCHDOG_STARTED = False
_STATE_PROVIDER: Callable[[], dict] | None = None
_GUI_THREAD_IDENT: int | None = None


def record_gui_tick(event_name: str = "scheduler_probe") -> None:
    """Call from the GUI thread on every existing lightweight periodic
    tick (e.g. the pre-existing 250ms scheduler probe timer). In-memory
    only -- no file I/O on this path, so it stays cheap on a hot timer.
    """
    with _GUI_HEARTBEAT_LOCK:
        _GUI_HEARTBEAT["last_tick_monotonic_ns"] = time.monotonic_ns()
        _GUI_HEARTBEAT["tick_sequence"] += 1
        _GUI_HEARTBEAT["last_event_name"] = event_name


def _next_sequence() -> int:
    global _SEQUENCE
    with _LOCK:
        _SEQUENCE += 1
        return _SEQUENCE


def _capture_all_thread_stacks() -> dict[str, Any]:
    try:
        frames = sys._current_frames()
    except Exception:
        return {}
    out: dict[str, Any] = {}
    try:
        threads = list(threading.enumerate())
    except Exception:
        threads = []
    for thread in threads:
        try:
            frame = frames.get(thread.ident)
            stack_lines = (
                traceback.format_stack(frame, limit=20) if frame is not None else []
            )
            out[str(thread.ident)] = {
                "thread_name": thread.name,
                "is_daemon": thread.daemon,
                "is_alive": thread.is_alive(),
                "stack": stack_lines,
            }
        except Exception:
            continue
    return out


def _write(event: str, **fields: Any) -> None:
    row = {
        "schema_version": "dvs.runtime.gui_hang_watchdog.v2",
        "event": event,
        "sequence": _next_sequence(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        **fields,
    }
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n"
        with _LOCK:
            with _PATH.open("a", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
    except Exception:
        pass


def _watchdog_loop(poll_interval_s: float) -> None:
    """Independent watcher with RC7.13 process-wide pause discrimination.

    Key idea:
    - REAL GUI-only stall: watchdog thread keeps polling near 250ms while the
      GUI heartbeat stops.
    - system/process-wide pause (sleep/hibernate/suspend/VM pause): the watchdog
      thread itself also wakes up late.

    We deliberately classify the latter as PROBABLE_PROCESS_WIDE_PAUSE rather
    than claiming OS_SLEEP, because the process cannot prove the external cause
    without OS power-event telemetry.
    """
    highest_threshold_crossed_ms = 0.0
    last_poll_monotonic = time.monotonic()
    last_process_cpu_s = time.process_time()

    while True:
        try:
            time.sleep(poll_interval_s)

            now_monotonic = time.monotonic()
            now_process_cpu_s = time.process_time()
            poll_gap_s = max(0.0, now_monotonic - last_poll_monotonic)
            process_cpu_delta_s = max(0.0, now_process_cpu_s - last_process_cpu_s)
            last_poll_monotonic = now_monotonic
            last_process_cpu_s = now_process_cpu_s

            expected_poll_s = max(0.001, float(poll_interval_s))
            process_wide_pause = poll_gap_s >= max(5.0, expected_poll_s * 8.0)

            with _GUI_HEARTBEAT_LOCK:
                last_tick_ns = _GUI_HEARTBEAT.get("last_tick_monotonic_ns")
                tick_sequence = _GUI_HEARTBEAT.get("tick_sequence")
                last_event_name = _GUI_HEARTBEAT.get("last_event_name")
            if last_tick_ns is None:
                continue

            now_ns = time.monotonic_ns()
            lag_ms = max(0.0, (now_ns - int(last_tick_ns)) / 1_000_000.0)

            pause_context = {
                "watchdog_poll_gap_ms": round(poll_gap_s * 1000.0, 3),
                "watchdog_expected_poll_ms": round(expected_poll_s * 1000.0, 3),
                "process_cpu_delta_ms": round(process_cpu_delta_s * 1000.0, 3),
                "suspension_classification": (
                    "PROBABLE_PROCESS_WIDE_PAUSE"
                    if process_wide_pause
                    else "GUI_THREAD_STALL_OR_BUSY"
                ),
            }

            if process_wide_pause:
                _write(
                    "process_wide_scheduling_gap_observed",
                    gui_observed_lag_ms=round(lag_ms, 3),
                    gui_tick_sequence=tick_sequence,
                    last_gui_event_name=last_event_name,
                    **pause_context,
                )

            if lag_ms < _THRESHOLDS_MS[0]:
                if highest_threshold_crossed_ms > 0.0:
                    _write(
                        "gui_hang_recovered",
                        observed_lag_ms=round(lag_ms, 3),
                        highest_threshold_crossed_ms=highest_threshold_crossed_ms,
                        gui_tick_sequence=tick_sequence,
                        **pause_context,
                    )
                    highest_threshold_crossed_ms = 0.0
                continue

            crossed = None
            for threshold in _THRESHOLDS_MS:
                if lag_ms >= threshold and threshold > highest_threshold_crossed_ms:
                    crossed = threshold
            if crossed is None:
                continue
            highest_threshold_crossed_ms = crossed

            state: dict = {}
            try:
                if _STATE_PROVIDER is not None:
                    state = _STATE_PROVIDER() or {}
            except Exception as exc:
                state = {"state_provider_error": repr(exc)}

            _write(
                "gui_hang_threshold_crossed",
                threshold_ms=crossed,
                observed_lag_ms=round(lag_ms, 3),
                gui_tick_sequence=tick_sequence,
                gui_thread_ident=_GUI_THREAD_IDENT,
                last_gui_event_name=last_event_name,
                python_thread_stacks=_capture_all_thread_stacks(),
                **pause_context,
                **state,
            )
        except Exception:
            # The watchdog itself must never die or crash the process.
            pass


def install_gui_hang_watchdog(
    gui_thread_ident: int,
    state_provider: Callable[[], dict] | None = None,
    poll_interval_s: float = 0.25,
) -> None:
    """Start the watchdog daemon thread once. Safe to call more than
    once; only the first call takes effect.
    """
    global _WATCHDOG_STARTED, _STATE_PROVIDER, _GUI_THREAD_IDENT
    with _WATCHDOG_LOCK:
        if _WATCHDOG_STARTED:
            return
        _WATCHDOG_STARTED = True
        _STATE_PROVIDER = state_provider
        _GUI_THREAD_IDENT = gui_thread_ident
        thread = threading.Thread(
            target=_watchdog_loop,
            args=(poll_interval_s,),
            name="dvs-gui-hang-watchdog",
            daemon=True,
        )
        thread.start()
    _write(
        "gui_hang_watchdog_installed",
        gui_thread_ident=gui_thread_ident,
        thresholds_ms=list(_THRESHOLDS_MS),
        poll_interval_s=poll_interval_s,
        suspension_discriminator="watchdog_poll_gap",
        schema_semantics="RC7.13",
    )
