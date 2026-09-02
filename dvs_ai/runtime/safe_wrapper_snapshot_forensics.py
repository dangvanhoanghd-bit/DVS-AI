"""DVS AI v2.4.3 RC6.10 — Safe Wrapper Snapshot Forensics.

This module intentionally avoids QObject.destroyed Python callbacks,
weakref.finalize hooks, DeferredDelete event filters, ownership changes,
deleteLater(), event-loop pumping and Shiboken introspection during C++
destruction.

It only records explicit snapshots at known Python control-flow boundaries.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PATH = Path("artifacts/runtime/safe_wrapper_snapshot_forensics.jsonl")
_LOCK = threading.Lock()
_SEQUENCE = 0


def _next_sequence() -> int:
    global _SEQUENCE
    with _LOCK:
        _SEQUENCE += 1
        return _SEQUENCE


def record_safe_wrapper_checkpoint(event: str, **extra: Any) -> None:
    row = {
        "schema_version": "dvs.runtime.safe_wrapper_snapshot_forensics.v1",
        "event": str(event),
        "sequence": _next_sequence(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_ns": time.monotonic_ns(),
        "pid": os.getpid(),
        "thread_ident": threading.get_ident(),
        **extra,
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
