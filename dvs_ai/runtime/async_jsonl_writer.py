"""DVS AI v2.4.3 RC6.16 — Async JSONL Writer.

Purpose: move blocking disk I/O (open/write/flush) for JSONL telemetry
files off whichever thread calls it -- most importantly the GUI thread,
where RC6.15's independent watchdog directly caught the Python stack
sitting inside this kind of synchronous file write during ~13% of
observed GUI stalls.

Design:
- One dedicated background daemon thread drains a bounded queue and
  performs the actual open("a")/write/flush/close sequence, in the same
  format as before (append mode, same json encoding), so on-disk output
  is unchanged -- only which thread performs the write changes.
- The producer-side call (enqueue_jsonl_write) is non-blocking: it does
  a queue.put_nowait() and returns immediately. If the queue is full
  (writer thread stalled far behind, e.g. disk genuinely unavailable),
  the write is dropped rather than blocking the calling thread -- for
  telemetry, losing a record under pathological conditions is an
  acceptable tradeoff for guaranteeing the GUI thread is never the one
  waiting on disk I/O.
- A single lock inside the writer thread naturally serializes writes to
  the same file across all callers, so the separate per-call lock this
  replaced is no longer needed.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

_QUEUE_MAXSIZE = 20000
_QUEUE: "queue.Queue[tuple[Path, dict]]" = queue.Queue(maxsize=_QUEUE_MAXSIZE)

_WRITER_LOCK = threading.Lock()
_WRITER_STARTED = False

_STATS_LOCK = threading.Lock()
_STATS = {
    "enqueued": 0,
    "written": 0,
    "dropped_queue_full": 0,
    "write_errors": 0,
}


def get_stats() -> dict:
    with _STATS_LOCK:
        return dict(_STATS)


def enqueue_jsonl_write(path: Path, payload: dict) -> bool:
    """Non-blocking. Returns True if the write was queued, False if the
    queue was full and the write was dropped. Never raises, never blocks
    the calling thread on disk I/O.
    """
    _ensure_writer_started()
    try:
        _QUEUE.put_nowait((Path(path), dict(payload)))
        with _STATS_LOCK:
            _STATS["enqueued"] += 1
        return True
    except queue.Full:
        with _STATS_LOCK:
            _STATS["dropped_queue_full"] += 1
        return False
    except Exception:
        return False


def _writer_loop() -> None:
    # One thread, so writes to the same file are naturally serialized --
    # no separate per-file lock is needed here.
    while True:
        path, payload = _QUEUE.get()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
                )
                handle.flush()
            with _STATS_LOCK:
                _STATS["written"] += 1
        except Exception:
            with _STATS_LOCK:
                _STATS["write_errors"] += 1
            # This writer thread must never die -- an unwritable path
            # should not stop future writes to other paths from being
            # attempted.
        finally:
            _QUEUE.task_done()


def _ensure_writer_started() -> None:
    global _WRITER_STARTED
    if _WRITER_STARTED:
        return
    with _WRITER_LOCK:
        if _WRITER_STARTED:
            return
        _WRITER_STARTED = True
        thread = threading.Thread(
            target=_writer_loop,
            name="dvs-async-jsonl-writer",
            daemon=True,
        )
        thread.start()


def flush_and_wait(timeout_s: float = 5.0) -> bool:
    """Best-effort: block the CALLING thread (never call this from the
    GUI thread during normal operation) until the queue drains or
    timeout_s elapses. Intended for shutdown paths that want queued
    telemetry to actually reach disk before the process exits, not for
    routine use.
    """
    deadline = time.monotonic() + max(0.0, timeout_s)
    while time.monotonic() < deadline:
        if _QUEUE.unfinished_tasks == 0:
            return True
        time.sleep(0.02)
    return _QUEUE.unfinished_tasks == 0
