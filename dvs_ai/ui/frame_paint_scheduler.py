from __future__ import annotations

import time
import weakref
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, QTimer


@dataclass
class PaintSchedulerMetrics:
    requests: int = 0
    deduplicated: int = 0
    painted: int = 0
    dropped: int = 0
    frames: int = 0
    last_frame_ms: float = 0.0
    max_frame_ms: float = 0.0
    queue_peak: int = 0


class FramePaintScheduler(QObject):
    """Coalesces QWidget.update() calls into a bounded GUI-frame commit.

    Requests for the same widget are deduplicated. Higher priority widgets are
    committed first, while a frame budget prevents one busy scan from flooding
    the Qt event loop. Remaining work is carried into the next frame.
    """

    def __init__(
        self,
        parent: Optional[QObject] = None,
        frame_interval_ms: int = 16,
        frame_budget_ms: float = 5.0,
    ):
        super().__init__(parent)
        self.frame_interval_ms = max(1, int(frame_interval_ms))
        self.frame_budget_ms = max(0.5, float(frame_budget_ms))
        self._pending: "OrderedDict[int, tuple[int, weakref.ReferenceType]]" = OrderedDict()
        self._sequence = 0
        self._closed = False
        self._metrics = PaintSchedulerMetrics()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.flush_frame)

    def request(self, widget, priority: int = 0) -> bool:
        if self._closed or widget is None:
            self._metrics.dropped += 1
            return False
        self._metrics.requests += 1
        key = id(widget)
        priority = int(priority)
        current = self._pending.get(key)
        if current is not None:
            self._metrics.deduplicated += 1
            old_priority, ref = current
            if priority > old_priority:
                self._pending[key] = (priority, ref)
            return False
        try:
            ref = weakref.ref(widget)
        except TypeError:
            self._metrics.dropped += 1
            return False
        self._sequence += 1
        self._pending[key] = (priority, ref)
        self._metrics.queue_peak = max(self._metrics.queue_peak, len(self._pending))
        if not self._timer.isActive():
            self._timer.start(self.frame_interval_ms)
        return True

    def flush_frame(self) -> int:
        if self._closed or not self._pending:
            return 0
        started = time.perf_counter()
        self._metrics.frames += 1
        painted = 0
        # Stable priority ordering: OrderedDict preserves request order for ties.
        batch = sorted(self._pending.items(), key=lambda item: item[1][0], reverse=True)
        self._pending.clear()
        for index, (key, (priority, ref)) in enumerate(batch):
            widget = ref()
            if widget is None:
                self._metrics.dropped += 1
                continue
            try:
                widget.update()
                painted += 1
                self._metrics.painted += 1
            except RuntimeError:
                # Qt wrapper already deleted.
                self._metrics.dropped += 1
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if elapsed_ms >= self.frame_budget_ms and index + 1 < len(batch):
                for _, (remaining_priority, remaining_ref) in batch[index + 1:]:
                    remaining_widget = remaining_ref()
                    if remaining_widget is not None:
                        self.request(remaining_widget, remaining_priority)
                break
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._metrics.last_frame_ms = elapsed_ms
        self._metrics.max_frame_ms = max(self._metrics.max_frame_ms, elapsed_ms)
        if self._pending and not self._timer.isActive():
            self._timer.start(self.frame_interval_ms)
        return painted

    def flush_all(self) -> int:
        total = 0
        while self._pending and not self._closed:
            total += self.flush_frame()
        return total

    def diagnostics(self) -> dict:
        return {
            "requests": self._metrics.requests,
            "deduplicated": self._metrics.deduplicated,
            "painted": self._metrics.painted,
            "dropped": self._metrics.dropped,
            "frames": self._metrics.frames,
            "pending": len(self._pending),
            "queue_peak": self._metrics.queue_peak,
            "last_frame_ms": round(self._metrics.last_frame_ms, 3),
            "max_frame_ms": round(self._metrics.max_frame_ms, 3),
            "frame_interval_ms": self.frame_interval_ms,
            "frame_budget_ms": self.frame_budget_ms,
        }

    def close(self, flush: bool = False):
        if flush:
            self.flush_all()
        self._closed = True
        self._timer.stop()
        self._pending.clear()
