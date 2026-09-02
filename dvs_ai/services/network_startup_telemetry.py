from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class NetworkStartupTelemetry:
    """Best-effort JSONL telemetry around snapshot network startup.

    Telemetry failures are deliberately non-fatal and never alter scan output.
    """

    def __init__(self, path: str | Path = "artifacts/runtime/network_startup.jsonl") -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def emit(self, event: str, **fields: Any) -> None:
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
        except Exception:
            # Diagnostic telemetry must never interrupt the trading pipeline.
            return


NETWORK_STARTUP = NetworkStartupTelemetry()
