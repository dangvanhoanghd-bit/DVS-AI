from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    import numpy as np
except Exception:  # pragma: no cover - telemetry must never break runtime
    np = None



def _forensic_mode_enabled() -> bool:
    return str(os.environ.get("DVS_FORENSIC_MODE", "0")).strip().lower() in {
        "1", "true", "yes", "on",
    }


class FrameOwnershipTelemetry:
    """Low-overhead, fail-open DataFrame ownership telemetry.

    Only active operations for the same (scan_id, symbol, timeframe) are
    compared. Runtime behavior and engine outputs are not changed.
    """

    def __init__(self, path: str | Path = "artifacts/runtime/frame_ownership.jsonl") -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._active: dict[int, dict[str, Any]] = {}
        self._next_token = 0
        self.enabled = _forensic_mode_enabled()

    @staticmethod
    def _frame_meta(frame: Any) -> dict[str, Any]:
        mgr = getattr(frame, "_mgr", None)
        try:
            shape = list(frame.shape)
        except Exception:
            shape = None
        try:
            columns = [str(value) for value in frame.columns]
        except Exception:
            columns = None
        return {
            "frame_id": id(frame),
            "manager_id": id(mgr) if mgr is not None else None,
            "shape": shape,
            "columns": columns,
        }

    def _emit(self, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            payload = dict(payload)
            payload.setdefault("wall_time", time.time())
            payload.setdefault("monotonic", time.monotonic())
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            with self._lock:
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line + "\n")
        except Exception:
            # Diagnostics are intentionally fail-open.
            return

    def checkout(
        self,
        frame: Any,
        *,
        scan_id: str,
        symbol: str,
        timeframe: str,
        cache_hit: bool,
    ) -> None:
        if not self.enabled:
            return
        self._emit({
            "event": "frame_checkout",
            "pid": os.getpid(),
            "thread_id": threading.get_ident(),
            "thread_name": threading.current_thread().name,
            "scan_id": str(scan_id or "UNKNOWN"),
            "symbol": str(symbol),
            "timeframe": str(timeframe),
            "cache_hit": bool(cache_hit),
            **self._frame_meta(frame),
        })

    @staticmethod
    def _shares_memory(left: Any, right: Any) -> bool | None:
        if np is None:
            return None
        try:
            left_array = left.to_numpy(copy=False)
            right_array = right.to_numpy(copy=False)
            return bool(np.shares_memory(left_array, right_array))
        except Exception:
            return None

    @contextmanager
    def operation(
        self,
        frame: Any,
        *,
        scan_id: str,
        symbol: str,
        timeframe: str,
        engine: str,
    ) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        started = time.monotonic()
        thread_id = threading.get_ident()
        meta = self._frame_meta(frame)
        record = {
            "pid": os.getpid(),
            "thread_id": thread_id,
            "thread_name": threading.current_thread().name,
            "scan_id": str(scan_id or "UNKNOWN"),
            "symbol": str(symbol),
            "timeframe": str(timeframe),
            "engine": str(engine),
            "started_monotonic": started,
            "frame": frame,
            **meta,
        }
        overlaps: list[dict[str, Any]] = []
        with self._lock:
            self._next_token += 1
            token = self._next_token
            for other_token, other in self._active.items():
                if (
                    other["symbol"] == record["symbol"]
                    and other["timeframe"] == record["timeframe"]
                    and other["thread_id"] != thread_id
                ):
                    same_frame = other["frame_id"] == record["frame_id"]
                    same_manager = (
                        other.get("manager_id") is not None
                        and other.get("manager_id") == record.get("manager_id")
                    )
                    if same_frame or same_manager:
                        shares = True if same_frame else self._shares_memory(frame, other["frame"])
                        overlaps.append({
                            "other_token": other_token,
                            "other_thread_id": other["thread_id"],
                            "other_thread_name": other["thread_name"],
                            "other_engine": other["engine"],
                            "other_frame_id": other["frame_id"],
                            "other_manager_id": other.get("manager_id"),
                            "other_scan_id": other["scan_id"],
                            "same_scan_id": other["scan_id"] == record["scan_id"],
                            "same_frame_id": same_frame,
                            "same_manager_id": same_manager,
                            "shares_memory": shares,
                            "overlap_ms_at_enter": max(
                                0.0,
                                (started-other["started_monotonic"])*1000.0,
                            ),
                        })
            self._active[token] = record

        self._emit({
            "event": "engine_enter",
            "token": token,
            **{k: v for k, v in record.items() if k != "frame"},
        })
        for overlap in overlaps:
            self._emit({
                "event": "FRAME_CONCURRENT_USE",
                "token": token,
                **{k: v for k, v in record.items() if k != "frame"},
                **overlap,
            })

        try:
            yield
        finally:
            ended = time.monotonic()
            after = self._frame_meta(frame)
            with self._lock:
                self._active.pop(token, None)
            self._emit({
                "event": "engine_exit",
                "token": token,
                "pid": os.getpid(),
                "thread_id": thread_id,
                "thread_name": threading.current_thread().name,
                "scan_id": record["scan_id"],
                "symbol": record["symbol"],
                "timeframe": record["timeframe"],
                "engine": record["engine"],
                "frame_id": record["frame_id"],
                "manager_id_before": record.get("manager_id"),
                "manager_id_after": after.get("manager_id"),
                "shape_before": record.get("shape"),
                "shape_after": after.get("shape"),
                "columns_before": record.get("columns"),
                "columns_after": after.get("columns"),
                "manager_changed": record.get("manager_id") != after.get("manager_id"),
                "shape_changed": record.get("shape") != after.get("shape"),
                "columns_changed": record.get("columns") != after.get("columns"),
                "duration_ms": max(0.0, (ended-started)*1000.0),
            })


FRAME_OWNERSHIP = FrameOwnershipTelemetry()
