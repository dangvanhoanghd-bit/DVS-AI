from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class UniverseLoaderTelemetry:
    """Append-only audit telemetry for RC6.4.5 async universe loading."""

    def __init__(self, path: str | Path = "artifacts/runtime/universe_loader.jsonl") -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._counters = {
            "universe_load_started_count": 0,
            "universe_load_finalized_count": 0,
            "universe_load_active_count": 0,
            "universe_load_superseded_count": 0,
            "late_result_discarded_count": 0,
        }

    def emit(self, event: str, **fields: Any) -> None:
        with self._lock:
            if event == "universe_loader_started":
                self._counters["universe_load_started_count"] += 1
                self._counters["universe_load_active_count"] += 1
            elif event == "universe_loader_finalized":
                self._counters["universe_load_finalized_count"] += 1
                self._counters["universe_load_active_count"] = max(
                    0, self._counters["universe_load_active_count"] - 1
                )
            elif event == "universe_loader_superseded":
                self._counters["universe_load_superseded_count"] += 1
            elif event == "universe_loader_late_result_discarded":
                self._counters["late_result_discarded_count"] += 1

            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "monotonic": time.monotonic(),
                "pid": os.getpid(),
                "thread_name": threading.current_thread().name,
                "event": event,
                **self._counters,
                **fields,
            }
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                    handle.flush()
            except Exception:
                # Telemetry must never change application behavior.
                return


UNIVERSE_LOADER_TELEMETRY = UniverseLoaderTelemetry()
