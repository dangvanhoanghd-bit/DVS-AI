"""DVS AI v2.4.3 RC6 — Shutdown Blocker Registry.

Observability only. This module does not stop, interrupt, quit, wait for,
terminate, delete, reparent, or otherwise mutate any thread or QObject.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_SCHEMA = "dvs.runtime.shutdown_blockers.v1"


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return "<unprintable>"


def _blocker_identity(row: dict[str, Any]) -> str:
    for key in ("object_id", "python_id", "cpp_address", "thread_ident"):
        value = row.get(key)
        if value not in (None, ""):
            return f"{key}:{_safe_text(value)}"
    name = _safe_text(row.get("object_name") or row.get("attribute") or row.get("class_name"))
    owner = _safe_text(row.get("owner"))
    return f"name:{owner}:{name}"


def _blocker_label(row: dict[str, Any]) -> str:
    name = _safe_text(row.get("object_name"))
    attribute = _safe_text(row.get("attribute"))
    class_name = _safe_text(row.get("class_name"))
    owner = _safe_text(row.get("owner"))

    label = name or attribute or class_name or "QThread"
    if owner and owner not in label:
        label = f"{owner}.{label}"
    return label


class ShutdownBlockerObserver:
    """Tracks only blocker identity and duration from externally supplied snapshots."""

    def __init__(
        self,
        *,
        out_path: str | Path = "artifacts/runtime/shutdown_blockers.jsonl",
        slow_threshold_s: float = 5.0,
    ) -> None:
        self._out_path = Path(out_path)
        self._slow_threshold_ns = int(max(0.1, float(slow_threshold_s)) * 1_000_000_000)
        self._started_ns = time.monotonic_ns()
        self._sequence = 0
        self._active: dict[str, dict[str, Any]] = {}
        self._completed = False
        self._write(
            "shutdown_blocker_observer_started",
            slow_threshold_ms=round(self._slow_threshold_ns / 1_000_000.0, 3),
        )

    def _write(self, event: str, **extra: Any) -> None:
        self._sequence += 1
        row = {
            "schema_version": _SCHEMA,
            "event": event,
            "sequence": self._sequence,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "monotonic_ns": time.monotonic_ns(),
            "pid": os.getpid(),
            "thread_ident": threading.get_ident(),
            **extra,
        }
        try:
            self._out_path.parent.mkdir(parents=True, exist_ok=True)
            with self._out_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
        except Exception:
            # Shutdown observability must never alter shutdown control flow.
            pass

    def update(
        self,
        survivors: Iterable[dict[str, Any]],
        *,
        phase: str,
        source: str = "qthread_registry",
    ) -> list[dict[str, Any]]:
        now_ns = time.monotonic_ns()
        normalized: list[dict[str, Any]] = []

        for source_row in survivors:
            row = dict(source_row)
            identity = _blocker_identity(row)
            label = _blocker_label(row)
            normalized.append({
                **row,
                "blocker_identity": identity,
                "blocker_label": label,
            })

            state = self._active.get(identity)
            if state is None:
                state = {
                    "identity": identity,
                    "label": label,
                    "first_seen_ns": now_ns,
                    "last_seen_ns": now_ns,
                    "slow_emitted": False,
                    "source_row": row,
                }
                self._active[identity] = state
                self._write(
                    "shutdown_blocker_registered",
                    phase=phase,
                    source=source,
                    blocker_identity=identity,
                    blocker_label=label,
                    blocker=row,
                )
            else:
                state["last_seen_ns"] = now_ns
                state["source_row"] = row

            elapsed_ns = now_ns - int(state["first_seen_ns"])
            if elapsed_ns >= self._slow_threshold_ns and not bool(state["slow_emitted"]):
                state["slow_emitted"] = True
                self._write(
                    "slow_shutdown_blocker",
                    phase=phase,
                    source=source,
                    blocker_identity=identity,
                    blocker_label=label,
                    elapsed_ms=round(elapsed_ns / 1_000_000.0, 3),
                    blocker=row,
                )

        current_ids = {row["blocker_identity"] for row in normalized}
        for identity in list(self._active):
            if identity in current_ids:
                continue
            state = self._active.pop(identity)
            elapsed_ns = now_ns - int(state["first_seen_ns"])
            self._write(
                "shutdown_blocker_cleared",
                phase=phase,
                source=source,
                blocker_identity=identity,
                blocker_label=state["label"],
                elapsed_ms=round(elapsed_ns / 1_000_000.0, 3),
                was_slow=bool(state["slow_emitted"]),
                blocker=state["source_row"],
            )

        self._write(
            "shutdown_blocker_snapshot",
            phase=phase,
            source=source,
            blocker_count=len(normalized),
            blocker_labels=[row["blocker_label"] for row in normalized],
            elapsed_ms=round((now_ns - self._started_ns) / 1_000_000.0, 3),
        )
        return normalized

    def active_labels(self, *, limit: int = 3) -> list[str]:
        labels = [str(state["label"]) for state in self._active.values()]
        labels.sort()
        return labels[:max(0, int(limit))]

    def complete(self, *, phase: str = "shutdown_complete") -> None:
        if self._completed:
            return
        self._completed = True
        now_ns = time.monotonic_ns()
        self._write(
            "shutdown_blocker_observer_completed",
            phase=phase,
            remaining_count=len(self._active),
            remaining_labels=self.active_labels(limit=100),
            total_elapsed_ms=round((now_ns - self._started_ns) / 1_000_000.0, 3),
        )


def format_shutdown_wait_text(
    blocker_count: int,
    blocker_labels: Iterable[str],
    *,
    compact: bool,
) -> str:
    labels = [str(label) for label in blocker_labels if str(label)]
    if labels:
        names = ", ".join(labels[:3])
        if blocker_count > len(labels[:3]):
            names += f", +{blocker_count - len(labels[:3])}"
        if compact:
            return f"Đang đóng an toàn… chờ: {names}."
        return f"Đang chờ tác vụ nền dừng an toàn: {names}. Ứng dụng sẽ tự đóng."
    if compact:
        return f"Đang đóng an toàn… còn {blocker_count} tác vụ nền."
    return f"Đang chờ {blocker_count} tác vụ nền dừng an toàn. Ứng dụng sẽ tự đóng."


_CLOSE_POLICY_BLOCKERS: dict[str, dict[str, Any]] = {
    "strict_teardown_failed": {
        "label": "Worker teardown",
        "thread_attribute": None,
        "category": "strict_teardown",
    },
    "outcome_resolution_timeout": {
        "label": "Outcome Resolution",
        "thread_attribute": None,
        "category": "outcome_resolution",
    },
    "outcome_resolution_exception": {
        "label": "Outcome Resolution",
        "thread_attribute": None,
        "category": "outcome_resolution",
    },
    "payload_footprint_shutdown_failed": {
        "label": "Payload Footprint Telemetry",
        "thread_attribute": None,
        "category": "payload_footprint",
    },
    "learning_refresh_shutdown_timeout": {
        "label": "Learning Refresh",
        "thread_attribute": "_learning_thread",
        "category": "learning_refresh",
    },
    "learning_refresh_shutdown_exception": {
        "label": "Learning Refresh",
        "thread_attribute": "_learning_thread",
        "category": "learning_refresh",
    },
    "qthread_registry_survivors": {
        "label": "QThread Registry",
        "thread_attribute": None,
        "category": "qthread_registry",
    },
    "scan_runtime_thread_timeout": {
        "label": "Scan Runtime",
        "thread_attribute": "_scan_runtime_thread",
        "category": "scan_runtime",
    },
}


def _thread_state(window: object | None, attribute: str | None) -> dict[str, Any]:
    if window is None or not attribute:
        return {
            "thread_attribute": attribute,
            "thread_present": None,
            "thread_running": None,
            "thread_object_name": None,
            "thread_python_id": None,
        }

    try:
        thread = getattr(window, attribute, None)
    except Exception:
        thread = None

    if thread is None:
        return {
            "thread_attribute": attribute,
            "thread_present": False,
            "thread_running": None,
            "thread_object_name": None,
            "thread_python_id": None,
        }

    try:
        running = bool(thread.isRunning())
    except Exception:
        running = None

    try:
        object_name = thread.objectName()
    except Exception:
        object_name = None

    return {
        "thread_attribute": attribute,
        "thread_present": True,
        "thread_running": running,
        "thread_object_name": object_name,
        "thread_python_id": hex(id(thread)),
    }


def close_policy_blocker_label(reason: str) -> str:
    spec = _CLOSE_POLICY_BLOCKERS.get(reason, {})
    return str(spec.get("label") or reason or "Unknown shutdown blocker")


def format_close_policy_blocker_text(reason: str) -> str:
    label = close_policy_blocker_label(reason)
    return f"Không thể đóng an toàn lúc này — đang chờ: {label}. Vui lòng chờ rồi đóng lại."


def record_close_policy_blocker(
    window: object | None,
    *,
    reason: str,
    phase: str = "close_policy_rejected",
    timeout_ms: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record an early close-policy blocker before registry polling is reached."""
    spec = _CLOSE_POLICY_BLOCKERS.get(reason, {})
    label = close_policy_blocker_label(reason)
    thread_state = _thread_state(window, spec.get("thread_attribute"))

    row = {
        "schema_version": _SCHEMA,
        "event": "close_policy_blocker_observed",
        "sequence": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "monotonic_ns": time.monotonic_ns(),
        "pid": os.getpid(),
        "thread_ident": threading.get_ident(),
        "phase": phase,
        "source": "close_policy",
        "reason": reason,
        "blocker_label": label,
        "category": spec.get("category"),
        "timeout_ms": timeout_ms,
        **thread_state,
        **(extra or {}),
    }

    out_path = Path("artifacts/runtime/shutdown_blockers.jsonl")
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
    except Exception:
        pass
    return row
