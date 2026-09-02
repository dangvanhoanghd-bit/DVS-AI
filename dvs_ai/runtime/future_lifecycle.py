from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FutureIdentity:
    scan_cycle_id: str
    executor_generation: int
    symbol: str


@dataclass
class FutureRuntime:
    identity: FutureIdentity
    submitted_at: float
    started_at: float | None = None
    finished_at: float | None = None
    state: str = "QUEUED"
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def mark_started(self) -> float:
        with self.lock:
            self.started_at = time.monotonic()
            self.state = "RUNNING"
            return max(0.0, self.started_at - self.submitted_at) * 1000.0

    def mark_finished(self) -> None:
        with self.lock:
            self.finished_at = time.monotonic()
            self.state = "FINISHED"


def orphan_threshold(max_workers: int) -> int:
    workers = max(1, int(max_workers))
    if workers == 1:
        return 1
    return min(workers, max(2, math.ceil(0.5 * workers)))


def classify_result_identity(
    identity: FutureIdentity,
    *,
    current_scan_cycle_id: str,
    current_executor_generation: int,
) -> str | None:
    if identity.scan_cycle_id != current_scan_cycle_id:
        return "STALE_FUTURE_RESULT_DISCARDED"
    if identity.executor_generation != current_executor_generation:
        return "QUARANTINED_EXECUTOR_RESULT_DISCARDED"
    return None
