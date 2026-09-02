from __future__ import annotations

import os
import time
from typing import Callable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class PerformanceOverlay(QFrame):
    """Live, non-modal UI telemetry panel.

    The overlay reads diagnostics from the real profiler, paint scheduler and
    table diff engine. It does not perform polling work outside the GUI thread
    and intentionally updates at a low frequency to avoid becoming a source of
    UI load itself.
    """

    def __init__(
        self,
        parent,
        *,
        profiler_provider: Callable[[], dict],
        scheduler_provider: Callable[[], dict],
        table_provider: Callable[[], dict],
        worker_provider: Optional[Callable[[], str]] = None,
        refresh_ms: int = 250,
    ):
        super().__init__(parent)
        self._profiler_provider = profiler_provider
        self._scheduler_provider = scheduler_provider
        self._table_provider = table_provider
        self._worker_provider = worker_provider or (lambda: "idle")
        self._last_sample_at = time.perf_counter()
        self._last_frame_count = 0
        self._fps = 0.0

        self.setObjectName("PerformanceOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setWindowFlags(Qt.WindowType.SubWindow)
        self.setMinimumWidth(265)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)
        self.title = QLabel("UI PERFORMANCE · LIVE")
        self.title.setObjectName("PerformanceOverlayTitle")
        self.body = QLabel()
        self.body.setObjectName("PerformanceOverlayBody")
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        layout.addWidget(self.title)
        layout.addWidget(self.body)

        self._timer = QTimer(self)
        self._timer.setInterval(max(100, int(refresh_ms)))
        self._timer.timeout.connect(self.refresh_metrics)
        self._timer.start()
        self.refresh_metrics()

    def set_overlay_visible(self, visible: bool) -> None:
        self.setVisible(bool(visible))
        if visible:
            self.raise_()
            self.reposition()
            self.refresh_metrics()

    def toggle(self) -> bool:
        visible = not self.isVisible()
        self.set_overlay_visible(visible)
        return visible

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        margin = 12
        x = max(margin, parent.width() - self.width() - margin)
        y = margin
        self.move(x, y)
        self.raise_()

    def refresh_metrics(self) -> dict:
        scheduler = dict(self._scheduler_provider() or {})
        profiler = dict(self._profiler_provider() or {})
        table = dict(self._table_provider() or {})

        now = time.perf_counter()
        frames = int(scheduler.get("frames", 0))
        elapsed = max(1e-6, now - self._last_sample_at)
        frame_delta = max(0, frames - self._last_frame_count)
        instant_fps = frame_delta / elapsed
        # Smoothing keeps the panel readable during bursty repaint workloads.
        self._fps = instant_fps if self._fps <= 0 else (0.35 * instant_fps + 0.65 * self._fps)
        self._last_sample_at = now
        self._last_frame_count = frames

        memory_mb = self._memory_mb()
        current_section = str(profiler.get("current_section", "IDLE"))
        lag_ms = float(profiler.get("last_event_loop_lag_ms", 0.0))
        max_lag_ms = float(profiler.get("max_event_loop_lag_ms", 0.0))
        pending = int(scheduler.get("pending", 0))
        frame_ms = float(scheduler.get("last_frame_ms", 0.0))
        max_frame_ms = float(scheduler.get("max_frame_ms", 0.0))
        dedup = int(scheduler.get("deduplicated", 0))
        changed = int(table.get("cells_changed", 0))
        checked = int(table.get("cells_checked", 0))
        update_ms = float(table.get("last_update_ms", 0.0))
        worker = self._worker_provider()

        lines = [
            f"FPS (paint): {self._fps:5.1f}   Frame: {frame_ms:5.2f} ms",
            f"Frame max: {max_frame_ms:5.2f} ms   Queue: {pending}",
            f"Event lag: {lag_ms:5.1f} ms   Max: {max_lag_ms:5.1f} ms",
            f"Paint dedup: {dedup}   Worker: {worker}",
            f"Cell diff: {changed}/{checked}   Last: {update_ms:5.2f} ms",
            f"Section: {current_section}",
        ]
        if memory_mb is not None:
            lines.append(f"Memory RSS: {memory_mb:,.1f} MB")
        self.body.setText("\n".join(lines))
        self.setProperty("health", self._health(lag_ms, frame_ms, pending))
        self.style().unpolish(self)
        self.style().polish(self)
        return {
            "fps": round(self._fps, 2),
            "frame_ms": frame_ms,
            "event_loop_lag_ms": lag_ms,
            "pending": pending,
            "worker": worker,
            "memory_mb": memory_mb,
        }

    @staticmethod
    def _health(lag_ms: float, frame_ms: float, pending: int) -> str:
        if lag_ms >= 300.0 or frame_ms >= 16.0 or pending >= 20:
            return "critical"
        if lag_ms >= 120.0 or frame_ms >= 8.0 or pending >= 8:
            return "warning"
        return "good"

    @staticmethod
    def _memory_mb() -> Optional[float]:
        try:
            import resource

            rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            # Linux reports KiB; macOS reports bytes.
            if os.name == "posix" and rss > 0:
                if rss > 10_000_000:
                    return rss / (1024.0 * 1024.0)
                return rss / 1024.0
        except Exception:
            return None
        return None

    def close_overlay(self) -> None:
        self._timer.stop()
        self.hide()
