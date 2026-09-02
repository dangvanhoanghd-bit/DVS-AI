from __future__ import annotations

from collections import deque
from typing import Optional
import threading

from PySide6.QtCore import QObject, QThread, Signal, Slot


class _LiveEpisodeCaptureWorker(QObject):
    completed = Signal(object, object, object)
    failed = Signal(object, str)

    def __init__(self, capture_service) -> None:
        super().__init__()
        self.capture_service = capture_service

    @Slot(object)
    def capture_one(self, analysis) -> None:
        try:
            identity = self.capture_service.capture_with_identity(analysis)
            self.completed.emit(analysis, identity.episode_id, identity)
        except Exception as exc:
            self.failed.emit(
                analysis,
                f"{type(exc).__name__}: {exc}",
            )


class LiveEpisodeCaptureRunner(QObject):
    """Persistent single-worker queue for non-blocking episode capture.

    GUI submissions are O(1). Captures execute serially on one long-lived
    QThread so SQLite writes never block MainWindow.on_result() and are not
    allowed to overlap with one another.
    """

    capture_completed = Signal(object, object, object)
    capture_failed = Signal(object, str)
    capture_rejected = Signal(object, str)
    _dispatch = Signal(object)

    def __init__(
        self,
        capture_service,
        parent: Optional[QObject] = None,
        *,
        max_pending: int = 512,
    ) -> None:
        super().__init__(parent)
        if max_pending < 0:
            raise ValueError("max_pending must be non-negative")
        self._thread = QThread(self)
        self._worker = _LiveEpisodeCaptureWorker(capture_service)
        self._worker.moveToThread(self._thread)
        self._dispatch.connect(self._worker.capture_one)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._thread.finished.connect(self._worker.deleteLater)
        self._queue = deque()
        self._active = False
        self._closed = False
        self._max_pending = int(max_pending)
        self._state_lock = threading.RLock()
        self._thread.start()

    def submit(self, analysis) -> bool:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("LiveEpisodeCaptureRunner is closed")
            if self._active:
                if len(self._queue) >= self._max_pending:
                    self.capture_rejected.emit(analysis, "QUEUE_FULL")
                    return False
                self._queue.append(analysis)
                return True
            self._start(analysis)
            return True

    def _start(self, analysis) -> None:
        self._active = True
        self._dispatch.emit(analysis)

    @Slot(object, object, object)
    def _on_completed(self, analysis, episode_id, candidate_id) -> None:
        self.capture_completed.emit(analysis, episode_id, candidate_id)
        self._advance()

    @Slot(object, str)
    def _on_failed(self, analysis, message: str) -> None:
        self.capture_failed.emit(analysis, message)
        self._advance()

    def _advance(self) -> None:
        with self._state_lock:
            self._active = False
            if self._queue and not self._closed:
                self._start(self._queue.popleft())

    @property
    def pending_count(self) -> int:
        with self._state_lock:
            return len(self._queue) + (1 if self._active else 0)

    def close(self, timeout_ms: int = 5000) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._queue.clear()
        self._thread.quit()
        self._thread.wait(timeout_ms)
