"""Application-level GUI event-loop blocker attribution.

Sprint A2 V2.2 diagnostic-only instrumentation.

The implementation deliberately avoids synchronous file I/O on the GUI thread.
QApplication.notify() records only in-memory timing/state and enqueues bounded
records to a background writer. A watchdog thread samples the GUI Python stack
when the GUI pulse is overdue or an individual Qt event remains active.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
from typing import Any, Deque, Dict, Optional

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_type_name(event_type: int) -> str:
    try:
        return QEvent.Type(event_type).name
    except Exception:
        return f"Type_{event_type}"


def _safe_object_name(receiver: QObject) -> str:
    try:
        return str(receiver.objectName() or "")[:160]
    except Exception:
        return ""


def _format_stack(frame: Any, limit: int = 32) -> list[str]:
    if frame is None:
        return []
    try:
        return [line.rstrip("\n") for line in traceback.format_stack(frame, limit=limit)]
    except Exception as exc:
        return [f"<stack_unavailable:{type(exc).__name__}:{exc}>"]


@dataclass
class _ActiveEvent:
    sequence: int
    event_type: int
    event_name: str
    receiver_class: str
    receiver_object_name: str
    entry_ns: int
    thread_ident: int


class _AsyncJsonlWriter:
    def __init__(self, path: Path, *, max_queue: int = 4096) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._queue: Deque[Dict[str, Any]] = deque(maxlen=max_queue)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._dropped = 0
        self._thread = threading.Thread(
            target=self._run,
            name="dvs-gui-event-forensics-writer",
            daemon=True,
        )
        self._thread.start()

    def publish(self, record: Dict[str, Any]) -> None:
        with self._lock:
            if len(self._queue) == self._queue.maxlen:
                self._dropped += 1
            self._queue.append(record)
        self._wake.set()

    def close(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=max(0.0, timeout))

    def _drain(self) -> list[Dict[str, Any]]:
        with self._lock:
            records = list(self._queue)
            self._queue.clear()
            dropped = self._dropped
            self._dropped = 0
        if dropped:
            records.insert(0, {
                "schema_version": "dvs.gui_event_loop_forensics.v1",
                "event": "writer_queue_drop",
                "timestamp_utc": _utc_now(),
                "monotonic_ns": time.monotonic_ns(),
                "dropped_count": dropped,
            })
        return records

    def _run(self) -> None:
        while not self._stop.is_set() or self._queue:
            self._wake.wait(0.5)
            self._wake.clear()
            records = self._drain()
            if not records:
                continue
            try:
                with self.path.open("a", encoding="utf-8", buffering=1) as handle:
                    for record in records:
                        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            except Exception:
                # Diagnostic telemetry must never terminate the application.
                pass


class InstrumentedApplication(QApplication):
    """QApplication subclass that attributes slow Qt event dispatches."""

    SLOW_EVENT_MS = 25.0
    PULSE_INTERVAL_MS = 100
    PULSE_LATE_MS = 250.0
    WATCHDOG_SAMPLE_AFTER_MS = 1000.0
    WATCHDOG_INTERVAL_S = 0.25

    def __init__(self, argv: list[str], *, runtime_root: Path | str = Path("artifacts/runtime")) -> None:
        super().__init__(argv)
        self._forensics_lock = threading.RLock()
        self._active_event: Optional[_ActiveEvent] = None
        self._event_sequence = 0
        self._gui_thread_ident = threading.get_ident()
        self._last_notify_progress_ns = time.monotonic_ns()
        self._last_pulse_ns = self._last_notify_progress_ns
        self._expected_pulse_ns = self._last_pulse_ns + self.PULSE_INTERVAL_MS * 1_000_000
        self._watchdog_stop = threading.Event()
        self._event_counts: Counter[str] = Counter()
        self._event_total_ns: Counter[str] = Counter()
        self._event_max_ns: Dict[str, int] = {}
        self._window_started_ns = time.monotonic_ns()
        self._writer = _AsyncJsonlWriter(Path(runtime_root) / "gui_event_loop_forensics.jsonl")

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(self.PULSE_INTERVAL_MS)
        self._pulse_timer.timeout.connect(self._on_pulse)
        self._pulse_timer.start()

        self._watchdog = threading.Thread(
            target=self._watchdog_loop,
            name="dvs-gui-event-loop-watchdog",
            daemon=True,
        )
        self._watchdog.start()
        self.aboutToQuit.connect(self.close_forensics)
        self._publish("forensics_started", {
            "pid": os.getpid(),
            "gui_thread_ident": self._gui_thread_ident,
            "slow_event_threshold_ms": self.SLOW_EVENT_MS,
            "pulse_interval_ms": self.PULSE_INTERVAL_MS,
            "watchdog_sample_after_ms": self.WATCHDOG_SAMPLE_AFTER_MS,
        })

    def _publish(self, event: str, fields: Dict[str, Any]) -> None:
        record = {
            "schema_version": "dvs.gui_event_loop_forensics.v1",
            "event": event,
            "timestamp_utc": _utc_now(),
            "monotonic_ns": time.monotonic_ns(),
            **fields,
        }
        self._writer.publish(record)

    def notify(self, receiver: QObject, event: QEvent) -> bool:  # type: ignore[override]
        entry_ns = time.perf_counter_ns()
        dispatch_thread_ident = threading.get_ident()
        is_gui_dispatch = dispatch_thread_ident == self._gui_thread_ident
        event_type = int(event.type())
        event_name = _event_type_name(event_type)
        receiver_class = type(receiver).__name__
        object_name = _safe_object_name(receiver)
        try:
            receiver_thread = receiver.thread()
            receiver_thread_ident = int(id(receiver_thread)) if receiver_thread is not None else None
        except Exception:
            receiver_thread_ident = None
        sequence = 0
        if is_gui_dispatch:
            with self._forensics_lock:
                self._event_sequence += 1
                sequence = self._event_sequence
                self._active_event = _ActiveEvent(
                    sequence=sequence,
                    event_type=event_type,
                    event_name=event_name,
                    receiver_class=receiver_class,
                    receiver_object_name=object_name,
                    entry_ns=entry_ns,
                    thread_ident=dispatch_thread_ident,
                )
        success = False
        try:
            result = super().notify(receiver, event)
            success = True
            return result
        finally:
            exit_ns = time.perf_counter_ns()
            elapsed_ns = max(0, exit_ns - entry_ns)
            elapsed_ms = elapsed_ns / 1_000_000.0
            if is_gui_dispatch:
                key = f"{receiver_class}:{event_name}"
                with self._forensics_lock:
                    self._last_notify_progress_ns = time.monotonic_ns()
                    self._event_counts[key] += 1
                    self._event_total_ns[key] += elapsed_ns
                    self._event_max_ns[key] = max(elapsed_ns, self._event_max_ns.get(key, 0))
                    if self._active_event and self._active_event.sequence == sequence:
                        self._active_event = None
                if elapsed_ms > self.SLOW_EVENT_MS:
                    self._publish("event_dispatch_slow", {
                        "sequence": sequence,
                        "event_type": event_type,
                        "event_name": event_name,
                        "receiver_class": receiver_class,
                        "receiver_object_name": object_name,
                        "dispatch_ms": round(elapsed_ms, 6),
                        "success": success,
                        "dispatch_thread_ident": dispatch_thread_ident,
                        "gui_thread_ident": self._gui_thread_ident,
                        "receiver_thread_ident": receiver_thread_ident,
                        "is_gui_dispatch": True,
                    })

    def _on_pulse(self) -> None:
        now_ns = time.monotonic_ns()
        with self._forensics_lock:
            expected_ns = self._expected_pulse_ns
            self._last_pulse_ns = now_ns
            self._expected_pulse_ns = now_ns + self.PULSE_INTERVAL_MS * 1_000_000
        late_ms = max(0.0, (now_ns - expected_ns) / 1_000_000.0)
        if late_ms > self.PULSE_LATE_MS:
            self._publish("event_loop_pulse_late", {
                "pulse_late_ms": round(late_ms, 6),
                "threshold_ms": self.PULSE_LATE_MS,
            })
        if now_ns - self._window_started_ns >= 1_000_000_000:
            self._publish_window_summary(now_ns)

    def _publish_window_summary(self, now_ns: int) -> None:
        with self._forensics_lock:
            counts = self._event_counts
            totals = self._event_total_ns
            maxima = self._event_max_ns
            self._event_counts = Counter()
            self._event_total_ns = Counter()
            self._event_max_ns = {}
            started_ns = self._window_started_ns
            self._window_started_ns = now_ns
        top = sorted(
            counts,
            key=lambda key: (totals.get(key, 0), maxima.get(key, 0)),
            reverse=True,
        )[:12]
        self._publish("event_dispatch_window", {
            "window_ms": round((now_ns - started_ns) / 1_000_000.0, 3),
            "event_count": int(sum(counts.values())),
            "top_events": [
                {
                    "key": key,
                    "count": counts[key],
                    "total_ms": round(totals[key] / 1_000_000.0, 6),
                    "max_ms": round(maxima[key] / 1_000_000.0, 6),
                }
                for key in top
            ],
        })

    def _watchdog_loop(self) -> None:
        last_sample_key: tuple[int, int] | None = None
        while not self._watchdog_stop.wait(self.WATCHDOG_INTERVAL_S):
            now_ns = time.monotonic_ns()
            with self._forensics_lock:
                active = self._active_event
                pulse_age_ms = (now_ns - self._last_pulse_ns) / 1_000_000.0
                notify_age_ms = (now_ns - self._last_notify_progress_ns) / 1_000_000.0
            active_elapsed_ms = None
            if active is not None:
                active_elapsed_ms = (time.perf_counter_ns() - active.entry_ns) / 1_000_000.0
            blocked = pulse_age_ms >= self.WATCHDOG_SAMPLE_AFTER_MS
            active_long = active_elapsed_ms is not None and active_elapsed_ms >= self.WATCHDOG_SAMPLE_AFTER_MS
            if not (blocked or active_long):
                last_sample_key = None
                continue
            sequence = active.sequence if active else 0
            bucket = int(max(pulse_age_ms, active_elapsed_ms or 0.0) // 250)
            sample_key = (sequence, bucket)
            if sample_key == last_sample_key:
                continue
            last_sample_key = sample_key
            frame = sys._current_frames().get(self._gui_thread_ident)
            self._publish("event_loop_watchdog_sample", {
                "pulse_age_ms": round(pulse_age_ms, 6),
                "notify_progress_age_ms": round(notify_age_ms, 6),
                "active_event": None if active is None else {
                    "sequence": active.sequence,
                    "event_type": active.event_type,
                    "event_name": active.event_name,
                    "receiver_class": active.receiver_class,
                    "receiver_object_name": active.receiver_object_name,
                    "elapsed_ms": round(active_elapsed_ms or 0.0, 6),
                },
                "gui_python_stack": _format_stack(frame),
            })

    def close_forensics(self) -> None:
        if self._watchdog_stop.is_set():
            return
        self._watchdog_stop.set()
        try:
            self._pulse_timer.stop()
        except Exception:
            pass
        self._watchdog.join(timeout=1.0)
        self._publish("forensics_stopped", {
            "last_event_sequence": self._event_sequence,
        })
        self._writer.close(timeout=2.0)
