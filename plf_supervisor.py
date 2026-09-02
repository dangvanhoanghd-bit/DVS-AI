"""External Process Lifetime Forensics supervisor for DVS AI.

This module is intentionally executed as a process separate from the Qt/Python
application. It launches ``run.py`` as a child, waits outside the child process,
and persists the child exit status even when in-process telemetry cannot run.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dvs_ai.diagnostics.windows_minidump_debugger import debug_child

SCHEMA = "dvs.process_lifetime_forensics.v1"
KNOWN_WINDOWS_STATUS = {
    0x00000000: "SUCCESS",
    0x00000001: "GENERIC_FAILURE_OR_EXPLICIT_EXIT_1",
    0x40000015: "STATUS_FATAL_APP_EXIT",
    0x80000003: "STATUS_BREAKPOINT",
    0xC0000005: "STATUS_ACCESS_VIOLATION",
    0xC000001D: "STATUS_ILLEGAL_INSTRUCTION",
    0xC0000094: "STATUS_INTEGER_DIVIDE_BY_ZERO",
    0xC00000FD: "STATUS_STACK_OVERFLOW",
    0xC0000135: "STATUS_DLL_NOT_FOUND",
    0xC0000139: "STATUS_ENTRYPOINT_NOT_FOUND",
    0xC0000142: "STATUS_DLL_INIT_FAILED",
    0xC0000374: "STATUS_HEAP_CORRUPTION",
    0xC0000409: "STATUS_STACK_BUFFER_OVERRUN_OR_FAIL_FAST",
    0xC000041D: "STATUS_FATAL_USER_CALLBACK_EXCEPTION",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass


def read_build_id(root: Path) -> str:
    try:
        return (root / "BUILD_ID.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return "UNKNOWN"


def normalize_exit_code(return_code: int) -> dict[str, Any]:
    unsigned_32 = return_code & 0xFFFFFFFF
    signed_32 = unsigned_32 if unsigned_32 < 0x80000000 else unsigned_32 - 0x100000000
    status_name = KNOWN_WINDOWS_STATUS.get(unsigned_32)
    if return_code == 0:
        classification = "CLEAN_EXIT"
    elif status_name and unsigned_32 >= 0x80000000:
        classification = "WINDOWS_NATIVE_ABNORMAL_TERMINATION"
    elif return_code < 0 and os.name != "nt":
        classification = "TERMINATED_BY_SIGNAL"
    else:
        classification = "NONZERO_PROCESS_EXIT"
    return {
        "exit_code_raw": return_code,
        "exit_code_signed_32": signed_32,
        "exit_code_unsigned_32": unsigned_32,
        "exit_code_hex": f"0x{unsigned_32:08X}",
        "windows_status_name": status_name,
        "classification": classification,
    }


def latest_marker_for_pid(marker_path: Path, pid: int) -> dict[str, Any] | None:
    if not marker_path.exists():
        return None
    latest = None
    try:
        with marker_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("pid") == pid:
                    latest = obj
    except OSError:
        return None
    return latest


def supervise(root: Path, child_args: list[str]) -> int:
    session_id = str(uuid.uuid4())
    artifacts = root / "artifacts" / "process_lifetime"
    journal = artifacts / "process_lifetime_forensics.jsonl"
    marker_path = root / "artifacts" / "runtime" / "process_exit_markers.jsonl"
    summary_path = artifacts / f"plf_session_{session_id}.json"
    stdout_path = artifacts / f"child_{session_id}.stdout.log"
    stderr_path = artifacts / f"child_{session_id}.stderr.log"
    command = [sys.executable, str(root / "run.py"), *child_args]

    append_jsonl(journal, {
        "schema": SCHEMA,
        "event": "supervisor_started",
        "timestamp_utc": utc_now(),
        "session_id": session_id,
        "supervisor_pid": os.getpid(),
        "parent_pid": os.getppid(),
        "build_id": read_build_id(root),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "command": command,
    })

    started_monotonic = time.monotonic()
    started_utc = utc_now()
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DEBUG_ONLY_THIS_PROCESS", 0x00000002)
        )

    # Preserve the visible console while also retaining native/Python stderr.
    with stdout_path.open("ab", buffering=0) as child_stdout, stderr_path.open("ab", buffering=0) as child_stderr:
        process = subprocess.Popen(
            command,
            cwd=str(root),
            stdin=None,
            stdout=child_stdout,
            stderr=child_stderr,
            creationflags=creationflags,
        )
        append_jsonl(journal, {
            "schema": SCHEMA,
            "event": "child_started",
            "timestamp_utc": started_utc,
            "session_id": session_id,
            "supervisor_pid": os.getpid(),
            "child_pid": process.pid,
            "build_id": read_build_id(root),
            "native_debugger_enabled": os.name == "nt",
        })

        native_capture = None
        if os.name == "nt":
            native_capture = debug_child(process, session_id, artifacts, read_build_id(root))
            return_code = process.wait(timeout=10)
        else:
            return_code = process.wait()

    ended_utc = utc_now()
    duration_s = max(0.0, time.monotonic() - started_monotonic)
    exit_info = normalize_exit_code(return_code)
    marker = latest_marker_for_pid(marker_path, process.pid)
    atexit_observed = bool(marker and marker.get("event") == "python_atexit")
    exit_record = {
        "schema": SCHEMA,
        "event": "child_exited",
        "timestamp_utc": ended_utc,
        "session_id": session_id,
        "supervisor_pid": os.getpid(),
        "child_pid": process.pid,
        "build_id": read_build_id(root),
        "started_utc": started_utc,
        "duration_seconds": round(duration_s, 6),
        "python_atexit_observed": atexit_observed,
        "latest_in_process_marker": marker,
        "native_crash_capture": native_capture,
        **exit_info,
    }
    append_jsonl(journal, exit_record)
    summary_path.write_text(json.dumps(exit_record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("\n==========================================")
    print(" DVS AI Process Lifetime Forensics")
    print("==========================================")
    print(f"Child PID      : {process.pid}")
    print(f"Duration       : {duration_s:.3f} s")
    print(f"Exit code      : {exit_info['exit_code_hex']} ({exit_info['exit_code_signed_32']})")
    print(f"Classification : {exit_info['classification']}")
    if exit_info.get("windows_status_name"):
        print(f"Windows status : {exit_info['windows_status_name']}")
    print(f"Python atexit  : {'observed' if atexit_observed else 'NOT observed'}")
    print(f"Evidence       : {summary_path}")
    return return_code


def main() -> int:
    parser = argparse.ArgumentParser(description="External DVS AI process supervisor")
    parser.add_argument("child_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    return supervise(root, list(args.child_args))


if __name__ == "__main__":
    raise SystemExit(main())
