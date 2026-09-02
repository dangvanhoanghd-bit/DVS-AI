from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QHeaderView, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from dvs_ai.services.integrity_alert_policy import IntegrityAlertPolicy
from dvs_ai.services.integrity_incident_ledger import IntegrityIncidentLedger


class _AlertWorker(QObject):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, source_db_path: str, ledger_path: str) -> None:
        super().__init__()
        self.ledger = IntegrityIncidentLedger(source_db_path, ledger_path)
        self.policy = IntegrityAlertPolicy(ledger_path)

    @Slot()
    def evaluate(self) -> None:
        try:
            ledger_snapshot = self.ledger.snapshot()
            self.ready.emit(self.policy.evaluate(ledger_snapshot))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    @Slot()
    def scan_and_evaluate(self) -> None:
        try:
            ledger_snapshot = self.ledger.capture()
            self.ready.emit(self.policy.evaluate(ledger_snapshot))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class IntegrityAlertWidget(QWidget):
    request_evaluate = Signal()
    request_scan = Signal()

    def __init__(self, source_db_path: str, ledger_path: str, parent=None) -> None:
        super().__init__(parent)
        self._thread = QThread(self)
        self._worker = _AlertWorker(source_db_path, ledger_path)
        self._worker.moveToThread(self._thread)
        self.request_evaluate.connect(self._worker.evaluate)
        self.request_scan.connect(self._worker.scan_and_evaluate)
        self._worker.ready.connect(self._render)
        self._worker.failed.connect(self._fail)
        self._last_urgent_signature: tuple[str, ...] = ()
        self._build()
        self._thread.start()
        self.evaluate()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.banner = QLabel("Integrity alerts: loading…")
        top.addWidget(self.banner)
        top.addStretch(1)
        refresh = QPushButton("Đánh giá ledger")
        refresh.clicked.connect(self.evaluate)
        top.addWidget(refresh)
        scan = QPushButton("Kiểm tra mới & cảnh báo")
        scan.clicked.connect(self.scan_and_evaluate)
        top.addWidget(scan)
        layout.addLayout(top)

        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(170)
        layout.addWidget(self.summary)

        tabs = QTabWidget()
        self.alerts = QTableWidget(0, 10)
        self.alerts.setHorizontalHeaderLabels([
            "Alert", "Severity", "Code", "Entity", "ID", "Age", "Occurrences",
            "Recurrences", "State", "Reason"
        ])
        self.alerts.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.alerts.horizontalHeader().setStretchLastSection(True)
        tabs.addTab(self.alerts, "Active Alerts")

        self.events = QTableWidget(0, 6)
        self.events.setHorizontalHeaderLabels([
            "Time", "Event", "Previous", "Current", "Incident Key", "Reason"
        ])
        self.events.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.events.horizontalHeader().setStretchLastSection(True)
        tabs.addTab(self.events, "Alert History")
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
    def evaluate(self) -> None:
        self.banner.setText("Integrity alerts: evaluating…")
        self.request_evaluate.emit()

    @Slot()
    def scan_and_evaluate(self) -> None:
        self.banner.setText("Integrity alerts: scanning…")
        self.request_scan.emit()

    @Slot(object)
    def _render(self, payload: dict[str, Any]) -> None:
        counts = payload.get("level_counts", {})
        self.banner.setText(
            f"Integrity alerts: {payload.get('status')} · Urgent {counts.get('URGENT', 0)} · "
            f"Alert {counts.get('ALERT', 0)} · Watch {counts.get('WATCH', 0)} · Notice {counts.get('NOTICE', 0)}"
        )
        transitions = payload.get("transitions", {})
        self.summary.setPlainText(json.dumps({
            "policy_version": payload.get("policy_version"),
            "new": len(transitions.get("new", [])),
            "escalated": len(transitions.get("escalated", [])),
            "deescalated": len(transitions.get("deescalated", [])),
            "cleared": len(transitions.get("cleared", [])),
            "policy": payload.get("policy", {}),
            "notes": payload.get("notes", []),
        }, ensure_ascii=False, indent=2))

        rows = payload.get("alerts", [])
        self.alerts.setRowCount(len(rows))
        for r, item in enumerate(rows):
            values = [
                item.get("alert_level", ""), item.get("severity", ""), item.get("code", ""),
                item.get("entity", ""), item.get("entity_id", ""), self._age(item.get("age_seconds", 0)),
                item.get("occurrence_count", 0), item.get("recurrence_count", 0), item.get("state", ""),
                "; ".join(item.get("alert_reasons", [])),
            ]
            for c, value in enumerate(values):
                self.alerts.setItem(r, c, QTableWidgetItem(str(value)))

        events = payload.get("events", [])
        self.events.setRowCount(len(events))
        for r, item in enumerate(events):
            try:
                reason = "; ".join(json.loads(item.get("reason_json", "[]")))
            except Exception:
                reason = str(item.get("reason_json", ""))
            values = [item.get("event_time", ""), item.get("event_type", ""), item.get("previous_level", ""),
                      item.get("current_level", ""), item.get("incident_key", ""), reason]
            for c, value in enumerate(values):
                self.events.setItem(r, c, QTableWidgetItem(str(value)))

        urgent_signature = tuple(sorted(str(row.get("incident_key")) for row in rows if row.get("alert_level") == "URGENT"))
        urgent_changed = urgent_signature and urgent_signature != self._last_urgent_signature
        self._last_urgent_signature = urgent_signature
        if urgent_changed:
            QMessageBox.warning(
                self,
                "DVS AI Integrity Alert",
                f"Có {len(urgent_signature)} cảnh báo URGENT cần kiểm tra.\n"
                "Đây là cảnh báo chỉ đọc; hệ thống không tự sửa dữ liệu hoặc thay đổi Decision Engine.",
            )

    @Slot(str)
    def _fail(self, message: str) -> None:
        QMessageBox.warning(self, "Integrity Alert Policy", message)

    def close(self, timeout_ms: int = 5000) -> None:
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(timeout_ms)
