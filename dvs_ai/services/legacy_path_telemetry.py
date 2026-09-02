from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

_LOG = logging.getLogger(__name__)
_LOCK = Lock()
_COUNTS: dict[str, int] = {}


def emit_legacy_sql_path_used(module: str, caller: str, query_type: str,
                              log_path: str | Path = "logs/legacy_sql_path.jsonl") -> None:
    """Emit observe-only telemetry whenever a deprecated storage path is used."""
    key = f"{module}:{caller}:{query_type}"
    with _LOCK:
        _COUNTS[key] = _COUNTS.get(key, 0) + 1
        count = _COUNTS[key]
    event = {
        "event": "LEGACY_SQL_PATH_USED",
        "module": module,
        "caller": caller,
        "query_type": query_type,
        "count": count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _LOG.warning("LEGACY_SQL_PATH_USED %s", json.dumps(event, sort_keys=True))
    try:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    except OSError:
        _LOG.exception("Unable to persist legacy-path telemetry")


def legacy_path_counts() -> dict[str, int]:
    with _LOCK:
        return dict(_COUNTS)
