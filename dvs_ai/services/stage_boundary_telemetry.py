from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _forensic_mode_enabled() -> bool:
    return str(os.environ.get("DVS_FORENSIC_MODE", "0")).strip().lower() in {
        "1", "true", "yes", "on",
    }


class StageBoundaryTelemetry:
    """Best-effort JSONL checkpoints with observable write integrity."""

    def __init__(self, path: str | Path = "artifacts/runtime/stage_boundary.jsonl") -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self.producer_emit_count = 0
        self.successful_write_count = 0
        self.write_error_count = 0
        self.last_error_type: str | None = None
        self.last_error_utc: str | None = None
        self._last_error_log_monotonic = 0.0
        self.enabled = _forensic_mode_enabled()

    def snapshot_counters(self) -> dict[str, Any]:
        if not self.enabled:
            return {
                "enabled": False,
                "producer_emit_count": 0,
                "successful_write_count": 0,
                "write_error_count": 0,
                "last_error_type": None,
                "last_error_utc": None,
            }
        with self._lock:
            return {
                "producer_emit_count": self.producer_emit_count,
                "successful_write_count": self.successful_write_count,
                "write_error_count": self.write_error_count,
                "last_error_type": self.last_error_type,
                "last_error_utc": self.last_error_utc,
            }

    def emit(self, event: str, **fields: Any) -> None:
        if not self.enabled:
            return
        with self._lock:
            self.producer_emit_count += 1
        record = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "monotonic_s": round(time.monotonic(), 6),
            "event": str(event),
            "pid": os.getpid(),
            "thread_id": threading.get_ident(),
            "thread_name": threading.current_thread().name,
            **fields,
        }
        try:
            line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                    handle.flush()
                self.successful_write_count += 1
        except Exception as exc:
            now_utc = datetime.now(timezone.utc).isoformat()
            now_mono = time.monotonic()
            with self._lock:
                self.write_error_count += 1
                self.last_error_type = type(exc).__name__
                self.last_error_utc = now_utc
                should_log = now_mono - self._last_error_log_monotonic >= 60.0
                if should_log:
                    self._last_error_log_monotonic = now_mono
            if should_log:
                log.warning("stage_boundary write failed (%s): %s", type(exc).__name__, exc)


STAGE_BOUNDARY = StageBoundaryTelemetry()
