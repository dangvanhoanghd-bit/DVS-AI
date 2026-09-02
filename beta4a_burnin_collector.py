from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
import traceback
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "data" / "dvs_paper_trades.db"
DEFAULT_LOG = ROOT / "logs" / "dvs_ai.log"
OUTPUT_ROOT = ROOT / "artifacts" / "beta4a_burnin"
DEFAULT_RUNTIME_DIR = ROOT / "artifacts" / "runtime"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_table_counts(db_path: Path) -> dict[str, int]:
    if not db_path.is_file():
        return {}
    counts: dict[str, int] = {}
    uri = f"file:{db_path.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=2.0) as conn:
            names = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            for name in names:
                escaped = name.replace('"', '""')
                try:
                    counts[name] = int(conn.execute(f'SELECT COUNT(*) FROM "{escaped}"').fetchone()[0])
                except sqlite3.Error:
                    continue
    except sqlite3.Error:
        return {}
    return counts


def sqlite_integrity(db_path: Path) -> str:
    if not db_path.is_file():
        return "MISSING"
    uri = f"file:{db_path.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=5.0) as conn:
            row = conn.execute("PRAGMA quick_check").fetchone()
            return str(row[0]) if row else "NO_RESULT"
    except sqlite3.Error as exc:
        return f"ERROR:{type(exc).__name__}:{exc}"



def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def read_runtime_telemetry(runtime_dir: Path, stale_seconds: float = 15.0) -> dict[str, Any]:
    status = read_json(runtime_dir / "runtime_status.json")
    heartbeat_path = runtime_dir / "heartbeat.json"
    heartbeat = read_json(heartbeat_path)
    if not status or not heartbeat:
        return {"available": True, "found": False, "state": "RUNTIME_NOT_STARTED"}
    try:
        age = max(0.0, time.time() - heartbeat_path.stat().st_mtime)
    except OSError:
        age = float("inf")
    process = heartbeat.get("process") or {}
    result = {
        "available": True,
        "found": age <= stale_seconds and heartbeat.get("status") in {"RUNNING", "STOPPING"},
        "state": "RUNTIME_CONNECTED" if age <= stale_seconds else "RUNTIME_HEARTBEAT_STALE",
        "heartbeat_age_seconds": round(age, 3),
        "pid": heartbeat.get("pid") or status.get("pid"),
        "version": heartbeat.get("version") or status.get("version"),
        "session_id": heartbeat.get("session_id") or status.get("session_id"),
        "rss_bytes": process.get("rss_bytes"),
        "cpu_percent": process.get("cpu_percent"),
        "thread_count": process.get("thread_count"),
        "open_files": process.get("open_files"),
        "ui": heartbeat.get("ui") or {},
        "queues": heartbeat.get("queues") or {},
        "source": "runtime_telemetry",
    }
    return result

def find_runtime_process() -> dict[str, Any]:
    try:
        import psutil  # type: ignore
    except Exception:
        return {"available": False, "reason": "psutil_not_installed"}

    current_pid = os.getpid()
    candidates: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            if proc.info["pid"] == current_pid:
                continue
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if "run.py" not in cmdline and "dvs_ai.app" not in cmdline:
                continue
            with proc.oneshot():
                candidates.append(
                    {
                        "pid": proc.pid,
                        "name": proc.name(),
                        "cmdline": cmdline,
                        "rss_bytes": proc.memory_info().rss,
                        "cpu_percent": proc.cpu_percent(interval=0.1),
                        "thread_count": proc.num_threads(),
                        "open_files": len(proc.open_files()),
                        "create_time": proc.create_time(),
                    }
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    if not candidates:
        return {"available": True, "found": False}
    candidates.sort(key=lambda item: item["create_time"], reverse=True)
    return {"available": True, "found": True, **candidates[0]}


def log_tail(path: Path, max_bytes: int = 256_000) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        data = handle.read()
    return data.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class Snapshot:
    timestamp_utc: str
    runtime: dict[str, Any]
    db_size_bytes: int | None
    db_mtime_ns: int | None
    table_counts: dict[str, int]
    log_size_bytes: int | None
    log_mtime_ns: int | None


def capture(db_path: Path, log_path: Path, runtime_dir: Path) -> Snapshot:
    db_stat = db_path.stat() if db_path.exists() else None
    log_stat = log_path.stat() if log_path.exists() else None
    return Snapshot(
        timestamp_utc=utc_now(),
        runtime=(lambda r: r if r.get("found") or r.get("state") == "RUNTIME_HEARTBEAT_STALE" else find_runtime_process())(read_runtime_telemetry(runtime_dir)),
        db_size_bytes=db_stat.st_size if db_stat else None,
        db_mtime_ns=db_stat.st_mtime_ns if db_stat else None,
        table_counts=safe_table_counts(db_path),
        log_size_bytes=log_stat.st_size if log_stat else None,
        log_mtime_ns=log_stat.st_mtime_ns if log_stat else None,
    )


def analyze(snapshots: list[Snapshot], db_integrity: str) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    runtimes = [item.runtime for item in snapshots if item.runtime.get("found")]
    if runtimes:
        rss_values = [int(item["rss_bytes"]) for item in runtimes]
        thread_values = [int(item["thread_count"]) for item in runtimes]
        if len(rss_values) >= 3 and rss_values[-1] > rss_values[0] * 1.5 and rss_values[-1] - rss_values[0] > 200 * 1024 * 1024:
            findings.append({"severity": "WARNING", "code": "MEMORY_GROWTH", "detail": "RSS grew by more than 50% and 200 MiB during capture."})
        if len(thread_values) >= 3 and thread_values[-1] > thread_values[0] + 10:
            findings.append({"severity": "WARNING", "code": "THREAD_GROWTH", "detail": "Thread count increased by more than 10."})
    else:
        findings.append({"severity": "INFO", "code": "RUNTIME_PROCESS_NOT_OBSERVED", "detail": "Collector could not observe the DVS process; install psutil or run with the application active."})

    if db_integrity.lower() != "ok":
        findings.append({"severity": "ERROR", "code": "SQLITE_QUICK_CHECK_FAILED", "detail": db_integrity})

    return {
        "status": "FAIL" if any(f["severity"] == "ERROR" for f in findings) else "REVIEW",
        "findings": findings,
        "snapshot_count": len(snapshots),
        "sqlite_quick_check": db_integrity,
    }



def collect_current_session_freeze_evidence(runtime_dir: Path, destination: Path) -> dict[str, Any]:
    """Copy only freeze evidence that matches the active runtime session and PID."""
    status = read_json(runtime_dir / "runtime_status.json") or {}
    session_id = str(status.get("session_id") or "")
    pid = status.get("pid")
    dump_raw = status.get("freeze_dump_path")
    metadata_raw = status.get("freeze_dump_metadata_path")
    result: dict[str, Any] = {
        "status": "NOT_AVAILABLE",
        "session_id": session_id or None,
        "pid": pid,
        "copied": [],
        "reason": None,
    }
    if not session_id or not dump_raw or not metadata_raw:
        result["reason"] = "runtime_status_missing_freeze_dump_identity"
        return result

    dump_path = Path(str(dump_raw))
    metadata_path = Path(str(metadata_raw))
    expected_dir = (runtime_dir / "freeze_dumps" / session_id).resolve()
    try:
        if dump_path.resolve().parent != expected_dir or metadata_path.resolve().parent != expected_dir:
            result["status"] = "STALE_OR_MISMATCHED"
            result["reason"] = "path_not_in_active_session_directory"
            return result
    except OSError as exc:
        result["status"] = "STALE_OR_MISMATCHED"
        result["reason"] = f"path_resolution_failed:{type(exc).__name__}"
        return result

    metadata = read_json(metadata_path)
    if not metadata:
        result["status"] = "STALE_OR_MISMATCHED"
        result["reason"] = "metadata_missing_or_invalid"
        return result
    if str(metadata.get("session_id") or "") != session_id or metadata.get("pid") != pid:
        result["status"] = "STALE_OR_MISMATCHED"
        result["reason"] = "metadata_session_or_pid_mismatch"
        return result
    if not dump_path.is_file():
        result["status"] = "STALE_OR_MISMATCHED"
        result["reason"] = "dump_missing"
        return result
    try:
        first_line = dump_path.open("r", encoding="utf-8", errors="replace").readline()
    except OSError as exc:
        result["status"] = "STALE_OR_MISMATCHED"
        result["reason"] = f"dump_read_failed:{type(exc).__name__}"
        return result
    if not first_line.startswith("DVS_FREEZE_DUMP_HEADER ") or f'"session_id": "{session_id}"' not in first_line:
        result["status"] = "STALE_OR_MISMATCHED"
        result["reason"] = "dump_header_mismatch"
        return result

    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dump_path, destination / "freeze_dump.log")
    shutil.copy2(metadata_path, destination / "freeze_dump_metadata.json")
    result["status"] = "VALID_CURRENT_SESSION"
    result["copied"] = ["freeze_dump.log", "freeze_dump_metadata.json"]
    return result

def write_csv(path: Path, snapshots: Iterable[Snapshot]) -> None:
    fields = ["timestamp_utc", "runtime_found", "pid", "rss_bytes", "cpu_percent", "thread_count", "open_files", "db_size_bytes", "log_size_bytes", "table_counts_json"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for snap in snapshots:
            runtime = snap.runtime
            writer.writerow(
                {
                    "timestamp_utc": snap.timestamp_utc,
                    "runtime_found": runtime.get("found", False),
                    "pid": runtime.get("pid"),
                    "rss_bytes": runtime.get("rss_bytes"),
                    "cpu_percent": runtime.get("cpu_percent"),
                    "thread_count": runtime.get("thread_count"),
                    "open_files": runtime.get("open_files"),
                    "db_size_bytes": snap.db_size_bytes,
                    "log_size_bytes": snap.log_size_bytes,
                    "table_counts_json": json.dumps(snap.table_counts, ensure_ascii=False, sort_keys=True),
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect evidence for the Beta 4A Windows burn-in audit.")
    parser.add_argument("--duration-minutes", type=float, default=120.0)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    args = parser.parse_args()

    if args.duration_minutes <= 0 or args.interval_seconds <= 0:
        parser.error("duration and interval must be positive")

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    session = args.output_root / session_id
    session.mkdir(parents=True, exist_ok=False)
    snapshots: list[Snapshot] = []
    deadline = time.monotonic() + args.duration_minutes * 60.0

    try:
        while True:
            snap = capture(args.db, args.log, args.runtime_dir)
            snapshots.append(snap)
            print(f"[{snap.timestamp_utc}] snapshot={len(snapshots)} runtime_found={snap.runtime.get('found', False)} state={snap.runtime.get('state', 'PROCESS_SCAN')}", flush=True)
            if time.monotonic() >= deadline:
                break
            time.sleep(min(args.interval_seconds, max(0.0, deadline - time.monotonic())))
    except KeyboardInterrupt:
        print("Capture stopped by user; evidence will still be packaged.", flush=True)
    except Exception:
        (session / "COLLECTOR_EXCEPTION.txt").write_text(traceback.format_exc(), encoding="utf-8")

    integrity = sqlite_integrity(args.db)
    report = {
        "schema_version": "beta4a.burnin.report.v1",
        "session_id": session_id,
        "created_at_utc": utc_now(),
        "duration_requested_minutes": args.duration_minutes,
        "interval_seconds": args.interval_seconds,
        "db_path": str(args.db.resolve()),
        "db_sha256": sha256_file(args.db),
        "log_path": str(args.log.resolve()),
        "runtime_dir": str(args.runtime_dir.resolve()),
        "analysis": analyze(snapshots, integrity),
        "snapshots": [asdict(item) for item in snapshots],
    }
    report_path = session / "BETA4A_BURNIN_REPORT.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    write_csv(session / "BETA4A_BURNIN_TIMESERIES.csv", snapshots)
    (session / "dvs_ai_log_tail.txt").write_text(log_tail(args.log), encoding="utf-8")
    if args.db.is_file():
        shutil.copy2(args.db, session / args.db.name)
    for telemetry_name in ("runtime_status.json", "heartbeat.json"):
        telemetry_path = args.runtime_dir / telemetry_name
        if telemetry_path.is_file():
            shutil.copy2(telemetry_path, session / telemetry_name)

    freeze_evidence = collect_current_session_freeze_evidence(args.runtime_dir, session)
    (session / "evidence_status.json").write_text(
        json.dumps(freeze_evidence, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    manifest = {
        "schema_version": "beta4a.burnin.manifest.v1",
        "created_at_utc": utc_now(),
        "files": {},
    }
    for file_path in sorted(path for path in session.iterdir() if path.is_file()):
        manifest["files"][file_path.name] = {"sha256": sha256_file(file_path), "size_bytes": file_path.stat().st_size}
    manifest_path = session / "BETA4A_BURNIN_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    archive = args.output_root / f"BETA4A_BURNIN_EVIDENCE_{session_id}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(session.iterdir()):
            if file_path.is_file():
                zf.write(file_path, arcname=file_path.name)
    checksum = sha256_file(archive)
    archive.with_suffix(archive.suffix + ".sha256").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    print(f"Evidence package: {archive}")
    print(f"SHA-256: {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
