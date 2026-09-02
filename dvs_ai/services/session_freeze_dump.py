from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class SessionFreezeDump:
    """Session-scoped freeze diagnostics in log-only mode.

    NATIVE2-F safety boundary:
    CPython ``faulthandler.dump_traceback_later(..., repeat=True)`` is deliberately
    disabled in the GUI process. On the audited Windows/Python 3.12 runtime it
    could enter ``Py_DumpTracebackThreads`` while scanner and Qt threads were
    active and terminate the process with access violation 0xC0000005.

    This component now preserves the same artifact paths and metadata contract,
    but performs no native all-thread traceback dump and creates no watchdog
    thread. Runtime/UI telemetry remains responsible for non-invasive stall data.
    """

    MODE = "log_only_native_dump_disabled"

    def __init__(self, *, runtime_root: Path, session_id: str, interval_seconds: float = 10.0) -> None:
        self.runtime_root = Path(runtime_root)
        self.session_id = str(session_id)
        self.interval_seconds = max(5.0, float(interval_seconds))
        self.session_dir = self.runtime_root / "freeze_dumps" / self.session_id
        self.dump_path = self.session_dir / "freeze_dump.log"
        self.metadata_path = self.session_dir / "freeze_dump_metadata.json"
        self._handle: TextIO | None = None
        self._started = False

    def start(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._handle = self.dump_path.open("w", encoding="utf-8", buffering=1)
        header = {
            "schema_version": "dvs.freeze_dump.v2",
            "session_id": self.session_id,
            "pid": os.getpid(),
            "started_at_utc": _utc_now(),
            "python_executable": sys.executable,
            "cwd": str(Path.cwd().resolve()),
            "dump_path": str(self.dump_path.resolve()),
            "interval_seconds_requested": self.interval_seconds,
            "mode": self.MODE,
            "native_traceback_timer_enabled": False,
            "all_threads_dump_enabled": False,
            "reason": "NATIVE2-F: isolate CPython Py_DumpTracebackThreads access violation",
        }
        self.metadata_path.write_text(
            json.dumps(header, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self._handle.write(
            "DVS_FREEZE_DIAGNOSTICS_HEADER "
            + json.dumps(header, ensure_ascii=False, sort_keys=True)
            + "\n"
        )
        self._handle.write(
            "NATIVE_TRACEBACK_DUMP_DISABLED "
            + json.dumps(
                {
                    "timestamp_utc": _utc_now(),
                    "mode": self.MODE,
                    "safe_telemetry_only": True,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
        self._handle.flush()
        self._started = True

    def stop(self) -> None:
        # Intentionally no faulthandler.cancel_dump_traceback_later(): this
        # component never schedules a native traceback timer in NATIVE2-F.
        if self._handle is not None:
            try:
                self._handle.write(
                    "DVS_FREEZE_DIAGNOSTICS_STOP "
                    + json.dumps(
                        {"timestamp_utc": _utc_now(), "mode": self.MODE},
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
                self._handle.flush()
                self._handle.close()
            finally:
                self._handle = None
        self._started = False
