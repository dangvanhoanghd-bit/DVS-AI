from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from dvs_ai.services.integrity_incident_ledger import IntegrityIncidentLedger


class _LedgerWorker(QObject):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, source_db_path: str, ledger_path: str) -> None:
        super().__init__()
        self.service = IntegrityIncidentLedger(source_db_path, ledger_path)

    @Slot()
    def capture(self) -> None:
        try:
            self.ready.emit(self.service.capture())
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    @Slot()
    def load(self) -> None:
        try:
            self.ready.emit(self.service.snapshot())
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class IntegrityIncidentLedgerWidget(QWidget):
    request_capture = Signal()
    request_load = Signal()

    def __init__(self, source_db_path: str, ledger_path: str, parent=None) -> None:
        super().__init__(parent)
        self._thread = QThread(self)
        self._worker = _LedgerWorker(source_db_path, ledger_path)
        self._worker.moveToThread(self._thread)
        self.request_capture.connect(self._worker.capture)
        self.request_load.connect(self._worker.load)
        self._worker.ready.connect(self._render)
        self._worker.failed.connect(self._fail)
        self._build()
        self._thread.start()
        self.load_history()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.status = QLabel("Integrity ledger: loading…")
        top.addWidget(self.status)
        top.addStretch(1)
        refresh = QPushButton("Tải lịch sử")
        refresh.clicked.connect(self.load_history)
        top.addWidget(refresh)
        capture = QPushButton("Kiểm tra & ghi snapshot")
        capture.clicked.connect(self.capture)
        top.addWidget(capture)
        layout.addLayout(top)

        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(150)
        layout.addWidget(self.summary)

        tabs = QTabWidget()
        self.incidents = QTableWidget(0, 10)
        self.incidents.setHorizontalHeaderLabels([
            "State", "Severity", "Code", "Entity", "ID", "First seen", "Last seen", "Age", "Occurrences", "Recurrences"
        ])
        self.incidents.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.incidents.horizontalHeader().setStretchLastSection(True)
        tabs.addTab(self.incidents, "Incident Ledger")

        self.history = QTableWidget(0, 5)
        self.history.setHorizontalHeaderLabels(["Generated", "Status", "Issues", "Severity counts", "Snapshot ID"])
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.history.horizontalHeader().setStretchLastSection(True)
        tabs.addTab(self.history, "Snapshot History")
        layout.addWidget(tabs, 1)

    @staticmethod
    def _age(seconds: int) -> str:
        seconds = max(0, int(seconds or 0))
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, _ = divmod(seconds, 60)
        if days:
            return f"{days}d {hours}h"
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    @Slot()
    def capture(self) -> None:
        self.status.setText("Integrity ledger: checking…")
        self.request_capture.emit()

    @Slot()
    def load_history(self) -> None:
        self.request_load.emit()

    @Slot(object)
    def _render(self, payload: dict[str, Any]) -> None:
        self.status.setText(
            f"Integrity ledger: {payload.get('status')} · Open {payload.get('open_incident_count', 0)} · "
            f"Resolved {payload.get('resolved_incident_count', 0)} · Snapshots {payload.get('snapshot_count', 0)}"
        )
        transitions = payload.get("transitions", {})
        self.summary.setPlainText(json.dumps({
            "latest_snapshot_id": payload.get("latest_snapshot_id"),
            "new": len(transitions.get("new", [])),
            "reopened": len(transitions.get("reopened", [])),
            "ongoing": len(transitions.get("ongoing", [])),
            "resolved": len(transitions.get("resolved", [])),
            "notes": payload.get("notes", []),
        }, ensure_ascii=False, indent=2))

        rows = payload.get("incidents", [])
        self.incidents.setRowCount(len(rows))
        keys = ("state", "severity", "code", "entity", "entity_id", "first_seen_at", "last_seen_at")
        for r, item in enumerate(rows):
            values = [item.get(k, "") for k in keys] + [
                self._age(item.get("age_seconds", 0)), item.get("occurrence_count", 0), item.get("recurrence_count", 0)
            ]
            for c, value in enumerate(values):
                self.incidents.setItem(r, c, QTableWidgetItem(str(value)))

        history = payload.get("snapshots", [])
        self.history.setRowCount(len(history))
        for r, item in enumerate(history):
            values = [
                item.get("generated_at", ""), item.get("source_status", ""), item.get("issue_count", 0),
                json.dumps(item.get("severity_counts", {}), sort_keys=True), item.get("snapshot_id", "")
            ]
            for c, value in enumerate(values):
                self.history.setItem(r, c, QTableWidgetItem(str(value)))

    @Slot(str)
    def _fail(self, message: str) -> None:
        QMessageBox.warning(self, "Integrity Incident Ledger", message)

    def close(self, timeout_ms: int = 5000) -> None:
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(timeout_ms)
