"""DVS AI v2.4.3 RC6.12B — Learning Snapshot Builder Forensics.

Observation only. Records aggregate counters for one
UnifiedOutcomeBuilder.build() call: how many input rows were processed,
how many times _snapshot_hash() was invoked, how many SQLite connections
and schema/feature_hash queries that actually took (expected to be ~1
connection + ~1 schema query per build() after the RC6.12B connection-
reuse fix, versus one connection + one schema query per record before
it), total elapsed time, and whether the build was cancelled midway.

This module never opens its own SQLite connection, never touches the
paper trades database, and never raises out of record_builder_build();
any failure to write is silently swallowed so instrumentation can never
change build() behavior or control flow.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PATH = Path("artifacts/runtime/learning_snapshot_builder_forensics.jsonl")
_LOCK = threading.Lock()
_SEQUENCE = 0


def _next_sequence() -> int:
    global _SEQUENCE
    with _LOCK:
        _SEQUENCE += 1
        return _SEQUENCE


def record_builder_build(
    *,
    input_rows: int,
    snapshot_hash_calls: int,
    sqlite_connections_opened: int,
    schema_queries: int,
    feature_hash_queries: int,
    build_elapsed_ms: float,
    cancelled: bool,
    **extra: Any,
) -> None:
    row = {
        "schema_version": "dvs.runtime.learning_snapshot_builder_forensics.v1",
        "event": "builder_build_complete",
        "sequence": _next_sequence(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_ns": time.monotonic_ns(),
        "pid": os.getpid(),
        "thread_ident": threading.get_ident(),
        "input_rows": int(input_rows),
        "snapshot_hash_calls": int(snapshot_hash_calls),
        "sqlite_connections_opened": int(sqlite_connections_opened),
        "schema_queries": int(schema_queries),
        "feature_hash_queries": int(feature_hash_queries),
        "build_elapsed_ms": float(build_elapsed_ms),
        "cancelled": bool(cancelled),
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
