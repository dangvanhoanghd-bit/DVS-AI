from __future__ import annotations

import hashlib
import json
import os
import platform
import queue
import shutil
import tempfile
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass


class _AtomicJsonWriter:
    """RC6.16 (causal fix): single-writer sink for _atomic_json_write().

    _atomic_json_write() performs mkstemp + json.dump + flush +
    os.fsync() + os.replace(). os.fsync() in particular forces a real
    disk write and is one of the slowest, least predictable syscalls
    under disk contention or antivirus scanning -- and every call site
    in this file (publish_heartbeat, publish_snapshot, _publish_status,
    _write_ab_manifest) previously ran on the GUI thread via
    heartbeat_timer/snapshot_timer QTimer callbacks. RC6.15's independent
    GUI hang watchdog directly caught the GUI thread's Python stack
    inside pathlib/tempfile/os calls matching this exact sequence during
    observed multi-second stalls.

    This mirrors the pre-existing _JsonlWriter class in this same file:
    one background daemon thread performs every _atomic_json_write()
    call; producers only queue (path, payload) and return immediately.
    Every call is preserved (not coalesced), including per-sequence
    snapshot files, so on-disk output is unchanged -- only which thread
    performs each write changes.
    """

    _STOP = object()

    def __init__(self) -> None:
        self._queue: queue.Queue[tuple[Path, dict[str, Any]] | object] = queue.Queue(maxsize=256)
        self._thread = threading.Thread(
            target=self._run,
            name=f"RuntimeAtomicJsonWriter-{os.getpid()}",
            daemon=True,
        )
        self._started = False
        self.dropped_records = 0
        self.write_errors = 0

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread.start()

    def submit(self, path: Path, payload: dict[str, Any]) -> None:
        if not self._started:
            # Writer never started (should not happen in normal
            # operation) -- fall back to a direct write rather than
            # silently losing an early snapshot/heartbeat/status write.
            _atomic_json_write(path, payload)
            return
        try:
            self._queue.put_nowait((path, dict(payload)))
        except queue.Full:
            self.dropped_records += 1

    def stop(self, timeout: float = 5.0) -> None:
        if not self._started:
            return
        try:
            self._queue.put(self._STOP, timeout=1.0)
        except queue.Full:
            return
        self._thread.join(timeout=max(0.1, float(timeout)))

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is self._STOP:
                break
            path, payload = item
            try:
                _atomic_json_write(path, payload)
            except Exception:
                self.write_errors += 1


class _JsonlWriter:
    """Single-writer JSONL sink. Producers never append to the file directly."""

    _STOP = object()

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._queue: queue.Queue[dict[str, Any] | object] = queue.Queue(maxsize=256)
        self._thread = threading.Thread(
            target=self._run,
            name=f"RuntimeMetricsWriter-{os.getpid()}",
            daemon=True,
        )
        self._started = False
        self.dropped_records = 0
        self.write_errors = 0

    def start(self) -> None:
        if self._started:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._started = True
        self._thread.start()

    def submit(self, payload: dict[str, Any]) -> None:
        if not self._started:
            return
        try:
            self._queue.put_nowait(dict(payload))
        except queue.Full:
            self.dropped_records += 1

    def stop(self, timeout: float = 5.0) -> None:
        if not self._started:
            return
        try:
            self._queue.put(self._STOP, timeout=1.0)
        except queue.Full:
            # Preserve shutdown responsiveness; the daemon thread remains safe.
            return
        self._thread.join(timeout=max(0.1, float(timeout)))

    def _run(self) -> None:
        try:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                while True:
                    item = self._queue.get()
                    if item is self._STOP:
                        break
                    try:
                        # One complete serialized record is written by one thread.
                        line = json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
                        handle.write(line)
                        handle.flush()
                    except Exception:
                        self.write_errors += 1
        except Exception:
            self.write_errors += 1


class RuntimeTelemetryExporter(QObject):
    """Session-isolated lightweight telemetry for controlled G1/G2 A/B tests."""

    SCHEMA_VERSION = "dvs.runtime.telemetry.v2"
    METRICS_SCHEMA_VERSION = "dvs.runtime.metrics.v2"
    EVENT_LOOP_INTERVAL_MS = 250
    NOT_RESPONDING_THRESHOLD_MS = 5000.0

    def __init__(
        self,
        *,
        root: Path,
        version: str,
        window: Any,
        build_label: str,
        heartbeat_seconds: float = 5.0,
        snapshot_seconds: float = 60.0,
        metrics_seconds: float = 20.0,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.root = Path(root)
        self.version = str(version)
        self.build_label = str(build_label)
        self.window = window
        self.session_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self.started_at_utc = _utc_now()
        self.started_monotonic = time.monotonic()
        self.sequence = 0
        self.metrics_sequence = 0
        self._process = None
        try:
            import psutil  # type: ignore
            self._process = psutil.Process(os.getpid())
            self._process.cpu_percent(interval=None)
        except Exception:
            self._process = None

        self.status_path = self.root / "runtime_status.json"
        self.heartbeat_path = self.root / "heartbeat.json"
        self.snapshots_root = self.root / "snapshots"
        self.snapshot_dir = self.snapshots_root / self.session_id
        self.metrics_path = self.root / f"runtime_metrics_{self.session_id}.jsonl"
        self.manifest_path = self.root / f"AB_TEST_MANIFEST_{self.session_id}.json"
        self.freeze_dump_path: Path | None = None
        self.freeze_dump_metadata_path: Path | None = None

        self._last_event_loop_tick = time.monotonic()
        self._event_loop_lag_ms = 0.0
        self._event_loop_lag_max_ms = 0.0
        self._event_loop_stall_count = 0
        self._not_responding_count = 0

        # RC7.13 — long-run observability only.
        #
        # `metrics_callback_gap_ms` records how late the GUI-side metrics timer
        # itself fired.  This is not called "sleep" because a long scheduling
        # gap can also come from hibernate, process suspension, VM pause, or a
        # heavily starved machine.  The independent watchdog supplies the
        # stronger GUI-only vs process-wide classification.
        self._last_metrics_callback_monotonic = time.monotonic()
        self._metrics_nominal_interval_s = max(5.0, float(metrics_seconds))
        self._active_runtime_seconds = 0.0
        self._rss_active_history = deque(maxlen=21600)

        self._writer = _JsonlWriter(self.metrics_path)
        self._atomic_writer = _AtomicJsonWriter()

        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.setInterval(max(1000, int(heartbeat_seconds * 1000)))
        self.heartbeat_timer.timeout.connect(self.publish_heartbeat)

        self.snapshot_timer = QTimer(self)
        self.snapshot_timer.setInterval(max(10_000, int(snapshot_seconds * 1000)))
        self.snapshot_timer.timeout.connect(self.publish_snapshot)

        # Measurement runs on the GUI thread; file I/O runs only on _JsonlWriter.
        self.metrics_timer = QTimer(self)
        self.metrics_timer.setInterval(max(5_000, int(metrics_seconds * 1000)))
        self.metrics_timer.timeout.connect(self.publish_runtime_metrics)

        self.event_loop_timer = QTimer(self)
        self.event_loop_timer.setTimerType(self.event_loop_timer.timerType())
        self.event_loop_timer.setInterval(self.EVENT_LOOP_INTERVAL_MS)
        self.event_loop_timer.timeout.connect(self._sample_event_loop_lag)

    def start(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._archive_previous_snapshot_sessions()
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._writer.start()
        self._atomic_writer.start()
        self._write_ab_manifest()
        self._publish_status("RUNNING")
        self._last_event_loop_tick = time.monotonic()
        self._last_metrics_callback_monotonic = time.monotonic()
        self.event_loop_timer.start()
        self.publish_heartbeat()
        self.publish_snapshot()
        self.publish_runtime_metrics()
        self.heartbeat_timer.start()
        self.snapshot_timer.start()
        self.metrics_timer.start()

    def stop(self) -> None:
        self.heartbeat_timer.stop()
        self.snapshot_timer.stop()
        self.metrics_timer.stop()
        self.event_loop_timer.stop()
        self.publish_runtime_metrics(status="STOPPING")
        self.publish_heartbeat(status="STOPPING")
        self._publish_status("STOPPED")
        self._writer.stop()
        self._atomic_writer.stop()

    def set_freeze_dump_paths(self, dump_path: Path, metadata_path: Path) -> None:
        self.freeze_dump_path = Path(dump_path)
        self.freeze_dump_metadata_path = Path(metadata_path)
        self._publish_status("RUNNING")

    def _archive_previous_snapshot_sessions(self) -> None:
        self.snapshots_root.mkdir(parents=True, exist_ok=True)
        archive_root = self.snapshots_root / "_archive"
        archive_root.mkdir(parents=True, exist_ok=True)
        for child in list(self.snapshots_root.iterdir()):
            if not child.is_dir() or child.name in {"_archive", self.session_id}:
                continue
            target = archive_root / child.name
            if target.exists():
                suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                target = archive_root / f"{child.name}__{suffix}"
                counter = 1
                while target.exists():
                    target = archive_root / f"{child.name}__{suffix}_{counter}"
                    counter += 1
            try:
                shutil.move(str(child), str(target))
            except OSError:
                # Telemetry must never prevent application startup.
                continue

    def _decision_engine_sha256(self) -> str | None:
        path = Path("dvs_ai/engines/decision_engine.py")
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return None

    def _write_ab_manifest(self) -> None:
        config = getattr(self.window, "config", None)
        watchlist = getattr(config, "watchlist", None)
        payload = {
            "schema_version": "dvs.performance_validation.manifest.v1",
            "build": self.build_label,
            "version": self.version,
            "session_id": self.session_id,
            "pid": os.getpid(),
            "start_time_utc": self.started_at_utc,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "decision_engine_sha256": self._decision_engine_sha256(),
            "metrics_interval_seconds": self.metrics_timer.interval() / 1000.0,
            "event_loop_probe_interval_ms": self.EVENT_LOOP_INTERVAL_MS,
            "not_responding_threshold_ms": self.NOT_RESPONDING_THRESHOLD_MS,
            "symbols": len(watchlist) if watchlist is not None else None,
            "scan_interval": getattr(config, "scan_interval", None),
            "validity_requirements": {
                "minimum_duration_minutes": 60,
                "maximum_duration_difference_percent": 15,
                "cpu_average_max_increase_percentage_points": 10,
            },
        }
        self._atomic_writer.submit(self.manifest_path, payload)

    def _publish_status(self, status: str) -> None:
        self._atomic_writer.submit(
            self.status_path,
            {
                "schema_version": self.SCHEMA_VERSION,
                "status": status,
                "pid": os.getpid(),
                "version": self.version,
                "build": self.build_label,
                "session_id": self.session_id,
                "started_at_utc": self.started_at_utc,
                "updated_at_utc": _utc_now(),
                "platform": platform.platform(),
                "heartbeat_path": str(self.heartbeat_path.resolve()),
                "snapshot_dir": str(self.snapshot_dir.resolve()),
                "runtime_metrics_path": str(self.metrics_path.resolve()),
                "ab_manifest_path": str(self.manifest_path.resolve()),
                "freeze_dump_path": str(self.freeze_dump_path.resolve()) if self.freeze_dump_path else None,
                "freeze_dump_metadata_path": str(self.freeze_dump_metadata_path.resolve()) if self.freeze_dump_metadata_path else None,
            },
        )

    def _safe_int_attr(self, names: tuple[str, ...]) -> int | None:
        for name in names:
            value = getattr(self.window, name, None)
            try:
                if callable(value):
                    value = value()
                if value is not None:
                    return int(value)
            except Exception:
                continue
        return None

    def _market_chart_paint_health(self) -> dict[str, Any]:
        """Read MarketChart paint counters without performing paint-path I/O."""
        chart = getattr(self.window, "market_chart", None)
        snapshot = getattr(chart, "paint_health_snapshot", None)
        if not callable(snapshot):
            return {
                "available": False,
                "reason": "market_chart_not_ready",
            }
        try:
            payload = dict(snapshot())
            return {
                "available": True,
                "invalid_value_count": int(payload.get("invalid_value_count", 0)),
                "reentrant_count": int(payload.get("reentrant_count", 0)),
                "failure_count": int(payload.get("failure_count", 0)),
                "last_issue": payload.get("last_issue"),
            }
        except Exception as exc:
            # Observability must never interrupt heartbeat publication.
            return {
                "available": False,
                "reason": f"{type(exc).__name__}:{exc}",
            }

    def _sample_process(self) -> dict[str, Any]:
        process: dict[str, Any] = {"available": self._process is not None}
        if self._process is not None:
            try:
                with self._process.oneshot():
                    mem = self._process.memory_info()
                    process.update(
                        {
                            "rss_bytes": int(mem.rss),
                            "cpu_percent": float(self._process.cpu_percent(interval=None)),
                            "thread_count": int(self._process.num_threads()),
                            "open_files": None,
                            "open_files_status": "disabled_gui_thread_safety",
                        }
                    )
            except Exception as exc:
                process = {"available": False, "error": f"{type(exc).__name__}:{exc}"}
        return process

    def _sample_event_loop_lag(self) -> None:
        now = time.monotonic()
        elapsed_ms = (now - self._last_event_loop_tick) * 1000.0
        self._last_event_loop_tick = now
        lag_ms = max(0.0, elapsed_ms - float(self.EVENT_LOOP_INTERVAL_MS))
        self._event_loop_lag_ms = round(lag_ms, 3)
        # V2.4.2: a multi-minute monotonic jump indicates that Windows
        # suspended the entire process. It must not inflate GUI freeze counts.
        suspend_threshold_ms = max(60_000.0, float(self.EVENT_LOOP_INTERVAL_MS) * 20.0)
        system_suspended = lag_ms >= suspend_threshold_ms
        if system_suspended:
            self._writer.submit({
                "schema_version": "dvs.runtime.system_suspend.v2.4.2",
                "timestamp_utc": _utc_now(),
                "event": "system_suspend_detected",
                "observed_gap_ms": round(lag_ms, 3),
                "classification": "EXTERNAL_SYSTEM_SUSPEND",
            })
        else:
            self._event_loop_lag_max_ms = max(self._event_loop_lag_max_ms, lag_ms)
            if lag_ms >= 500.0:
                self._event_loop_stall_count += 1
            if lag_ms >= self.NOT_RESPONDING_THRESHOLD_MS:
                self._not_responding_count += 1

    def _collect(self, status: str = "RUNNING") -> dict[str, Any]:
        process = self._sample_process()
        ui = {
            "last_event_loop_lag_ms": self._event_loop_lag_ms,
            "max_event_loop_lag_ms": round(self._event_loop_lag_max_ms, 3),
            "event_loop_stall_count": self._event_loop_stall_count,
            "not_responding_count": self._not_responding_count,
            "not_responding_threshold_ms": self.NOT_RESPONDING_THRESHOLD_MS,
        }
        return {
            "schema_version": self.SCHEMA_VERSION,
            "status": status,
            "pid": os.getpid(),
            "version": self.version,
            "build": self.build_label,
            "session_id": self.session_id,
            "started_at_utc": self.started_at_utc,
            "timestamp_utc": _utc_now(),
            "uptime_seconds": round(time.monotonic() - self.started_monotonic, 3),
            "sequence": self.sequence,
            "process": process,
            "ui": ui,
            "market_chart_paint_health": self._market_chart_paint_health(),
            "queues": {
                "pending_unified_identities": self._safe_int_attr(("pending_unified_identity_count", "_pending_unified_identity_count")),
                "worker_queue_depth": self._safe_int_attr(("worker_queue_depth", "_worker_queue_depth")),
            },
        }

    def publish_heartbeat(self, status: str = "RUNNING") -> None:
        self.sequence += 1
        self._atomic_writer.submit(self.heartbeat_path, self._collect(status=status))

    def publish_snapshot(self) -> None:
        payload = self._collect(status="RUNNING")
        path = self.snapshot_dir / f"snapshot_{self.sequence:08d}.json"
        self._atomic_writer.submit(path, payload)

    @staticmethod
    def _linear_slope_mib_per_hour(samples) -> float | None:
        """Least-squares RSS slope against active runtime, not wall time."""
        if samples is None or len(samples) < 3:
            return None
        xs = [float(row[0]) for row in samples]
        ys = [float(row[1]) / (1024.0 * 1024.0) for row in samples]
        x_mean = sum(xs) / len(xs)
        y_mean = sum(ys) / len(ys)
        denom = sum((x - x_mean) ** 2 for x in xs)
        if denom <= 0.0:
            return None
        slope_mib_per_second = (
            sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
            / denom
        )
        return round(slope_mib_per_second * 3600.0, 4)

    def _memory_trend(self, rss_bytes: int | None) -> dict[str, Any]:
        if rss_bytes is None:
            return {
                "active_runtime_seconds": round(self._active_runtime_seconds, 3),
                "samples": len(self._rss_active_history),
                "slope_mib_per_hour_30m": None,
                "slope_mib_per_hour_60m": None,
                "slope_mib_per_hour_120m": None,
            }

        active_now = float(self._active_runtime_seconds)
        self._rss_active_history.append((active_now, int(rss_bytes)))

        result = {
            "active_runtime_seconds": round(active_now, 3),
            "samples": len(self._rss_active_history),
        }
        for minutes in (30, 60, 120):
            cutoff = active_now - (minutes * 60.0)
            window = [row for row in self._rss_active_history if row[0] >= cutoff]
            result[f"slope_mib_per_hour_{minutes}m"] = self._linear_slope_mib_per_hour(window)
        return result

    def publish_runtime_metrics(self, status: str = "RUNNING") -> None:
        self.metrics_sequence += 1

        now_monotonic = time.monotonic()
        callback_delta_s = max(
            0.0, now_monotonic - float(self._last_metrics_callback_monotonic)
        )
        self._last_metrics_callback_monotonic = now_monotonic

        # Active-runtime accounting intentionally caps one callback interval.
        # A 3-hour machine sleep therefore does not make an RSS slope appear
        # artificially flat simply because wall time passed while no process
        # work occurred.
        active_increment_s = min(
            callback_delta_s,
            max(self._metrics_nominal_interval_s * 2.0, 10.0),
        )
        self._active_runtime_seconds += active_increment_s

        process = self._sample_process()
        memory_trend = self._memory_trend(process.get("rss_bytes"))
        payload = {
            "schema_version": self.METRICS_SCHEMA_VERSION,
            "timestamp_utc": _utc_now(),
            "session_id": self.session_id,
            "build": self.build_label,
            "pid": os.getpid(),
            "status": status,
            "sequence": self.metrics_sequence,
            "uptime_seconds": round(time.monotonic() - self.started_monotonic, 3),
            "cpu_percent": process.get("cpu_percent"),
            "rss_bytes": process.get("rss_bytes"),
            "thread_count": process.get("thread_count"),
            "metrics_callback_gap_ms": round(callback_delta_s * 1000.0, 3),
            "metrics_callback_gap_classification": (
                "LONG_PROCESS_SCHEDULING_GAP"
                if callback_delta_s >= max(30.0, self._metrics_nominal_interval_s * 3.0)
                else "NORMAL_INTERVAL"
            ),
            "memory_trend": memory_trend,
            "event_loop_lag_ms": self._event_loop_lag_ms,
            "event_loop_lag_max_ms": round(self._event_loop_lag_max_ms, 3),
            "event_loop_stall_count": self._event_loop_stall_count,
            "not_responding_count": self._not_responding_count,
            "not_responding_threshold_ms": self.NOT_RESPONDING_THRESHOLD_MS,
            "market_chart_paint_health": self._market_chart_paint_health(),
            "writer_queue_depth": self._writer._queue.qsize(),
            "writer_dropped_records": self._writer.dropped_records,
            "writer_errors": self._writer.write_errors,
        }
        self._writer.submit(payload)
