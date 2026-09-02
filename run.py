from __future__ import annotations

import atexit
import faulthandler
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dvs_ai.app import main


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _append_marker(event: str) -> None:
    try:
        path = Path(__file__).resolve().parent / "artifacts" / "runtime" / "process_exit_markers.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps({
                "schema": "dvs.process_exit_marker.v1",
                "event": event,
                "timestamp_utc": _utc_now(),
                "pid": os.getpid(),
            }, sort_keys=True) + "\n")
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
    except Exception:
        pass


def _install_fatal_dump() -> object | None:
    try:
        path = Path(__file__).resolve().parent / "artifacts" / "process_lifetime" / f"faulthandler_{os.getpid()}.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8")
        faulthandler.enable(file=handle, all_threads=True)
        return handle
    except Exception:
        return None


_FATAL_HANDLE = _install_fatal_dump()
_append_marker("python_process_started")
atexit.register(_append_marker, "python_atexit")


if __name__ == "__main__":
    raise SystemExit(main())
