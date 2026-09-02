"""DVS AI v2.4.3 RC6.6 — Learning Cooperative Return Telemetry.

This module records cancellation decisions. It never raises exceptions and
never controls QThread lifecycle.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PATH = Path("artifacts/runtime/learning_cooperative_return.jsonl")
_LOCK = threading.Lock()
_SEQUENCE = 0


def record_cooperative_return(event: str, **extra: Any) -> None:
    global _SEQUENCE
    with _LOCK:
        _SEQUENCE += 1
        sequence = _SEQUENCE
    row = {
        "schema_version": "dvs.runtime.learning_cooperative_return.v1",
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
