from __future__ import annotations

import atexit
import json
import os
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _forensic_mode_enabled() -> bool:
    return str(os.environ.get("DVS_FORENSIC_MODE", "0")).strip().lower() in {
        "1", "true", "yes", "on",
    }


class _GR01GuiCommitForensics:
    """Low-overhead asynchronous writer for GR-01A callback decomposition.

    Callback code builds one aggregate record and enqueues one JSON line only
    after the measured work completes. No disk I/O occurs inside GUI hot loops.
    """

    _SCHEMA = "dvs.runtime.gr01_gui_commit_forensics.v1"

    def __init__(self) -> None:
        self._path = Path("artifacts/runtime/gr01_gui_commit_forensics.jsonl")
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=10000)
        self._stop = threading.Event()
        self._dropped = 0
        self._writer: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self.enabled = _forensic_mode_enabled()
        if self.enabled:
            atexit.register(self.close)

    @staticmethod
    def _round_ms(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return round(float(value), 3)
        except (TypeError, ValueError):
            return None

    def _ensure_started(self) -> None:
        if self._writer is not None:
            return
        with self._start_lock:
            if self._writer is not None:
                return
            self._writer = threading.Thread(
                target=self._writer_loop,
                name="dvs-gr01-gui-forensics-writer",
                daemon=True,
            )
            self._writer.start()

    def emit(self, event: str, **fields: Any) -> None:
        if not self.enabled:
            return
        self._ensure_started()
        started_ns = time.perf_counter_ns()
        record = {
            "schema_version": self._SCHEMA,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "pid": os.getpid(),
            "event": str(event),
            "python_thread_ident": threading.get_ident(),
        }
        for key, value in fields.items():
            if key.endswith("_ms"):
                record[key] = self._round_ms(value)
            else:
                record[key] = value
        record.setdefault("queue_wait_ms", None)
        record.setdefault("data_prepare_ms", 0.0)
        record.setdefault("model_transform_ms", 0.0)
        record.setdefault("table_diff_ms", 0.0)
        record.setdefault("widget_create_ms", 0.0)
        record.setdefault("item_update_ms", 0.0)
        record.setdefault("layout_ms", 0.0)
        record.setdefault("repaint_request_ms", 0.0)
        record.setdefault("total_callback_ms", 0.0)
        record["telemetry_ms"] = 0.0

        # First serialization measures record construction/serialization cost;
        # the final line includes that telemetry cost and is queued once.
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        record["telemetry_ms"] = round((time.perf_counter_ns() - started_ns) / 1_000_000.0, 3)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        try:
            self._queue.put_nowait(line)
        except queue.Full:
            self._dropped += 1

    def _writer_loop(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8", buffering=1) as handle:
                while True:
                    try:
                        line = self._queue.get(timeout=0.25)
                    except queue.Empty:
                        if self._stop.is_set() and self._queue.empty():
                            break
                        continue
                    if line is None:
                        self._queue.task_done()
                        break
                    handle.write(line + "\n")
                    self._queue.task_done()
                handle.flush()
        except Exception:
            # Measurement must never affect runtime behavior.
            return

    def close(self) -> None:
        if not self.enabled:
            return
        if self._stop.is_set():
            return
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        writer = self._writer
        if writer is not None and writer.is_alive() and threading.current_thread() is not writer:
            writer.join(timeout=1.5)


GR01_GUI_FORENSICS = _GR01GuiCommitForensics()

__all__ = ["GR01_GUI_FORENSICS"]
