"""DVS AI v2.4.3 RC6.5 — Learning Refresh Stabilization Telemetry."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PATH = Path("artifacts/runtime/learning_refresh_stabilization.jsonl")
_LOCK = threading.Lock()
_SEQ = 0


def record_stabilization(event: str, **extra: Any) -> None:
    global _SEQ
    with _LOCK:
        _SEQ += 1
        sequence = _SEQ
    row = {
        "schema_version": "dvs.runtime.learning_refresh_stabilization.v1",
        "event": str(event),
        "sequence": sequence,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_ns": time.monotonic_ns(),
        "pid": os.getpid(),
        "thread_ident": threading.get_ident(),
        **extra,
    }
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        with _LOCK:
            with _PATH.open("a", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
    except Exception:
        pass
