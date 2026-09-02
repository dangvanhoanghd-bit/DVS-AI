from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit,
    QFileDialog, QMessageBox, QSizePolicy,
)

from dvs_ai.services.outcome_analytics import OutcomeAnalyticsService
from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore


class _SnapshotWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, db_path: str) -> None:
        super().__init__()
        self.db_path = db_path

    @Slot()
    def run(self) -> None:
        try:
            store = OutcomeInfrastructureStore(self.db_path)
            snapshot = OutcomeAnalyticsService(store).snapshot()
            self.completed.emit(snapshot)
        except Exception as exc:  # pragma: no cover - defensive GUI boundary
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class StatisticalDiagnosticsDashboard(QWidget):
    """Read-only statistical diagnostics. Never changes trading authority."""

    refresh_requested = Signal()

    def __init__(self, db_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db_path = str(db_path)
        self._snapshot: dict[str, Any] | None = None
        self._busy = False
        self._thread = QThread(self)
        self._worker = _SnapshotWorker(self.db_path)
        self._worker.moveToThread(self._thread)
        self.refresh_requested.connect(self._worker.run)
        self._worker.completed.connect(self._on_snapshot)
        self._worker.failed.connect(self._on_failure)
        self._thread.start()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Statistical Diagnostics · Episode Level")
        title.setStyleSheet("font-size:16px;font-weight:700")
        self.generated_label = QLabel("Chưa tải dữ liệu")
        self.refresh_button = QPushButton("Làm mới")
        self.export_json_button = QPushButton("Xuất JSON")
        self.export_html_button = QPushButton("Xuất HTML")
        self.refresh_button.clicked.connect(self.refresh)
        self.export_json_button.clicked.connect(lambda: self._export("json"))
        self.export_html_button.clicked.connect(lambda: self._export("html"))
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.generated_label)
        header.addWidget(self.refresh_button)
        header.addWidget(self.export_json_button)
        header.addWidget(self.export_html_button)
        layout.addLayout(header)

        cards = QGridLayout()
        self.cards: dict[str, QLabel] = {}
        specs = [
            ("status", "SAMPLE STATUS"),
            ("observed", "OBSERVED N"),
            ("ess", "CONSERVATIVE ESS"),
            ("clusters", "EVENT CLUSTERS"),
            ("largest", "LARGEST CLUSTER"),
            ("symbols", "UNIQUE SYMBOLS"),
        ]
        for index, (key, label) in enumerate(specs):
            frame = QFrame()
            frame.setObjectName("MetricCard")
            box = QVBoxLayout(frame)
            caption = QLabel(label)
            caption.setObjectName("MetricTitle")
            value = QLabel("—")
            value.setObjectName("MetricValue")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.addWidget(caption)
            box.addWidget(value)
            cards.addWidget(frame, index // 3, index % 3)
            self.cards[key] = value
        layout.addLayout(cards)

        tables = QHBoxLayout()
        self.cluster_table = self._table(["Cluster size", "Số cluster", "Episodes"])
        self.bootstrap_table = self._table(["Metric", "Lower 95%", "Upper 95%"])
        tables.addWidget(self._panel("Market-event cluster distribution", self.cluster_table), 3)
        tables.addWidget(self._panel("Clustered bootstrap intervals", self.bootstrap_table), 2)
        layout.addLayout(tables, 1)

        lower = QHBoxLayout()
        self.funnel_table = self._table(["Outcome", "Count"])
        self.calibration_table = self._table(["Confidence", "N", "Win rate", "Average R"])
        lower.addWidget(self._panel("Candidate outcome funnel", self.funnel_table), 2)
        lower.addWidget(self._panel("Calibration", self.calibration_table), 3)
        layout.addLayout(lower, 1)

        self.warning = QTextEdit()
        self.warning.setReadOnly(True)
        self.warning.setMaximumHeight(100)
        layout.addWidget(self._panel("Scientific boundary", self.warning))

    @staticmethod
    def _table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return table

    @staticmethod
    def _panel(title: str, widget: QWidget) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Panel")
        box = QVBoxLayout(frame)
        caption = QLabel(title)
        caption.setStyleSheet("font-weight:700;color:#cbd5e1")
        box.addWidget(caption)
        box.addWidget(widget, 1)
        return frame

    @Slot()
    def refresh(self) -> None:
        if self._busy or not self._thread.isRunning():
            return
        self._busy = True
        self.refresh_button.setEnabled(False)
        self.generated_label.setText("Đang tính toán…")
        self.refresh_requested.emit()

    @Slot(object)
    def _on_snapshot(self, snapshot: object) -> None:
        self._busy = False
        self.refresh_button.setEnabled(True)
        self._snapshot = dict(snapshot)
        self._render(self._snapshot)

    @Slot(str)
    def _on_failure(self, message: str) -> None:
        self._busy = False
        self.refresh_button.setEnabled(True)
        self.generated_label.setText("Không thể tải dữ liệu")
        self.warning.setPlainText(message)

    def _render(self, snapshot: dict[str, Any]) -> None:
        rel = snapshot.get("statistical_reliability", {})
        self.generated_label.setText(str(snapshot.get("generated_at", "—")))
        self.cards["status"].setText(str(rel.get("reliability_status", "UNOBSERVABLE")))
        self.cards["observed"].setText(str(rel.get("decisive_episode_count", 0)))
        self.cards["ess"].setText(str(rel.get("conservative_effective_sample_size", 0)))
        self.cards["clusters"].setText(str(rel.get("market_event_cluster_count", 0)))
        self.cards["largest"].setText(str(rel.get("largest_cluster_size", 0)))
        self.cards["symbols"].setText(str(rel.get("unique_symbol_count", 0)))

        distribution = rel.get("cluster_size_distribution", [])
        self.cluster_table.setRowCount(len(distribution))
        for row, item in enumerate(distribution):
            values = (item.get("cluster_size"), item.get("cluster_count"), item.get("episode_count"))
            for col, value in enumerate(values):
                self.cluster_table.setItem(row, col, QTableWidgetItem(str(value)))

        intervals = rel.get("clustered_bootstrap", {})
        interval_rows = [
            ("Win rate", intervals.get("win_rate_95")),
            ("Average realized R", intervals.get("average_realized_r_95")),
        ]
        self.bootstrap_table.setRowCount(len(interval_rows))
        for row, (name, bounds) in enumerate(interval_rows):
            lower, upper = (bounds or [None, None])
            values = (name, self._fmt(lower), self._fmt(upper))
            for col, value in enumerate(values):
                self.bootstrap_table.setItem(row, col, QTableWidgetItem(str(value)))

        funnel = snapshot.get("outcome_funnel", {})
        self.funnel_table.setRowCount(len(funnel))
        for row, (status, count) in enumerate(sorted(funnel.items())):
            self.funnel_table.setItem(row, 0, QTableWidgetItem(status))
            self.funnel_table.setItem(row, 1, QTableWidgetItem(str(count)))

        calibration = snapshot.get("calibration", [])
        self.calibration_table.setRowCount(len(calibration))
        for row, item in enumerate(calibration):
            values = (
                f"{item.get('lower')}-{item.get('upper')}",
                item.get("samples", 0),
                self._pct(item.get("actual_win_rate")),
                self._fmt(item.get("average_realized_r")),
            )
            for col, value in enumerate(values):
                self.calibration_table.setItem(row, col, QTableWidgetItem(str(value)))

        limitations = snapshot.get("known_limitations", {})
        boundary = snapshot.get("safety_boundary", {})
        self.warning.setPlainText(
            f"{rel.get('status_reason', '')}\n\n"
            f"Cross-Symbol Dependence: {limitations.get('cross_symbol_dependence', '')}\n\n"
            "READ-ONLY: Decision Engine frozen; automatic tuning disabled; "
            f"exchange-order capability={boundary.get('exchange_order_capability', False)}."
        )

    @staticmethod
    def _fmt(value: Any) -> str:
        return "—" if value is None else f"{float(value):.4f}"

    @staticmethod
    def _pct(value: Any) -> str:
        return "—" if value is None else f"{float(value) * 100:.1f}%"

    def _export(self, kind: str) -> None:
        suffix = ".json" if kind == "json" else ".html"
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất Statistical Diagnostics", f"outcome_analytics{suffix}",
            "JSON (*.json)" if kind == "json" else "HTML (*.html)",
        )
        if not path:
            return
        try:
            service = OutcomeAnalyticsService(OutcomeInfrastructureStore(self.db_path))
            output = service.export_json(Path(path)) if kind == "json" else service.export_html(Path(path))
            QMessageBox.information(self, "Đã xuất", str(output))
        except Exception as exc:
            QMessageBox.critical(self, "Xuất thất bại", f"{type(exc).__name__}: {exc}")

    def close(self, timeout_ms: int = 5000) -> None:
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(timeout_ms)
