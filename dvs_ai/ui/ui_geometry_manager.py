from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WindowGeometrySnapshot:
    width: int
    height: int
    maximized: bool
    fullscreen: bool
    tab_index: int
    outer_scroll: int
    detail_scroll: int
    score_scroll: int


class LayoutFreezeContext(AbstractContextManager):
    def __init__(self, widget: Optional[QWidget]):
        self.widget = widget
        self._was_enabled = True

    def __enter__(self):
        if self.widget is not None:
            self._was_enabled = self.widget.updatesEnabled()
            self.widget.setUpdatesEnabled(False)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.widget is not None:
            self.widget.setUpdatesEnabled(self._was_enabled)
            self.widget.update()
        return False


class UIGeometryManager(QObject):
    RESTORE_DELAYS_MS = (0, 40, 140)

    def __init__(self, window: QMainWindow):
        super().__init__(window)
        self.window = window
        self.initialized = False
        self.last_breakpoint = ""
        self.last_diagnostic: dict = {}

    def initialize_once(self) -> None:
        if self.initialized:
            return
        self.initialized = True

        screen = self.window.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()

        if not self.window.isMaximized() and not self.window.isFullScreen():
            target_width = min(
                available.width(),
                max(960, int(available.width() * 0.94)),
            )
            target_height = min(
                available.height(),
                max(640, int(available.height() * 0.92)),
            )
            self.window.resize(target_width, target_height)

        self.apply_breakpoint(self.window.width())
        self.log_diagnostic("startup")

    @staticmethod
    def breakpoint_for_width(width: int) -> str:
        if width < 1450:
            return "COMPACT"
        if width < 1850:
            return "STANDARD"
        return "WIDE"

    def apply_breakpoint(self, width: int) -> None:
        breakpoint = self.breakpoint_for_width(width)
        if breakpoint == self.last_breakpoint:
            return
        self.last_breakpoint = breakpoint

        right = getattr(self.window, "detail_right_panel", None)
        symbol = getattr(self.window, "header_symbol", None)

        if breakpoint == "COMPACT":
            right_min, right_max = 280, 390
            symbol_min, symbol_max = 80, 145
        elif breakpoint == "STANDARD":
            right_min, right_max = 300, 440
            symbol_min, symbol_max = 90, 175
        else:
            right_min, right_max = 320, 480
            symbol_min, symbol_max = 100, 195

        if right is not None:
            right.setMinimumWidth(right_min)
            right.setMaximumWidth(right_max)
        if symbol is not None:
            symbol.setMinimumWidth(symbol_min)
            symbol.setMaximumWidth(symbol_max)

        self.log_diagnostic(f"breakpoint:{breakpoint}")

    def capture_view_state(self) -> WindowGeometrySnapshot:
        window = self.window
        tabs = getattr(window, "tabs", None)
        outer = getattr(window, "detail_scroll_area", None)
        detail = getattr(window, "detail_text", None)
        score = getattr(window, "score_explain", None)

        return WindowGeometrySnapshot(
            width=window.width(),
            height=window.height(),
            maximized=window.isMaximized(),
            fullscreen=window.isFullScreen(),
            tab_index=tabs.currentIndex() if tabs is not None else 0,
            outer_scroll=(
                outer.verticalScrollBar().value()
                if outer is not None else 0
            ),
            detail_scroll=(
                detail.verticalScrollBar().value()
                if detail is not None else 0
            ),
            score_scroll=(
                score.verticalScrollBar().value()
                if score is not None else 0
            ),
        )

    @staticmethod
    def _restore_scroll(scroll_bar, value: int) -> None:
        maximum = max(0, scroll_bar.maximum())
        scroll_bar.setValue(max(0, min(int(value), maximum)))

    def restore_view_state(self, snapshot: WindowGeometrySnapshot) -> None:
        window = self.window
        tabs = getattr(window, "tabs", None)
        outer = getattr(window, "detail_scroll_area", None)
        detail = getattr(window, "detail_text", None)
        score = getattr(window, "score_explain", None)

        if tabs is not None and 0 <= snapshot.tab_index < tabs.count():
            tabs.setCurrentIndex(snapshot.tab_index)
        if outer is not None:
            self._restore_scroll(
                outer.verticalScrollBar(),
                snapshot.outer_scroll,
            )
        if detail is not None:
            self._restore_scroll(
                detail.verticalScrollBar(),
                snapshot.detail_scroll,
            )
        if score is not None:
            self._restore_scroll(
                score.verticalScrollBar(),
                snapshot.score_scroll,
            )

    def schedule_view_restore(
        self,
        snapshot: WindowGeometrySnapshot,
    ) -> None:
        for delay in self.RESTORE_DELAYS_MS:
            QTimer.singleShot(
                delay,
                lambda state=snapshot: self.restore_view_state(state),
            )

    def freeze(self, widget: Optional[QWidget]) -> LayoutFreezeContext:
        return LayoutFreezeContext(widget)

    def observe_resize(self, width: int, height: int) -> None:
        self.apply_breakpoint(width)
        self.last_diagnostic = {
            **self.last_diagnostic,
            "last_resize": (width, height),
            "maximized": self.window.isMaximized(),
            "fullscreen": self.window.isFullScreen(),
        }

    def log_diagnostic(self, reason: str) -> None:
        screen = self.window.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        diagnostic = {
            "reason": reason,
            "window": (self.window.width(), self.window.height()),
            "minimum": (
                self.window.minimumWidth(),
                self.window.minimumHeight(),
            ),
            "size_hint": (
                self.window.sizeHint().width(),
                self.window.sizeHint().height(),
            ),
            "screen": (
                available.width(),
                available.height(),
            ) if available else None,
            "maximized": self.window.isMaximized(),
            "fullscreen": self.window.isFullScreen(),
            "breakpoint": self.last_breakpoint,
        }
        splitter = getattr(self.window, "detail_splitter", None)
        if splitter is not None:
            diagnostic["detail_splitter"] = tuple(splitter.sizes())
        self.last_diagnostic = diagnostic
        logger.info("UI_LAYOUT_DIAGNOSTIC %s", diagnostic)
