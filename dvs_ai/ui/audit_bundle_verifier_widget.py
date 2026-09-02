from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from dvs_ai.services.audit_bundle_verifier import IndependentAuditBundleVerifier


class AuditBundleVerifierWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.service = IndependentAuditBundleVerifier()
        self.bundle_path: str | None = None
        self.report: dict | None = None

        layout = QVBoxLayout(self)
        title = QLabel("Audit Bundle Verification · Read-only · No import · No database write")
        title.setWordWrap(True)
        layout.addWidget(title)

        row = QHBoxLayout()
        open_button = QPushButton("Mở Bundle")
        open_button.clicked.connect(self._open)
        row.addWidget(open_button)
        verify_button = QPushButton("Xác minh")
        verify_button.clicked.connect(self._verify)
        row.addWidget(verify_button)
        self.strict_mode = QCheckBox("Strict: file ngoài manifest = FAIL")
        self.strict_mode.setToolTip("Normal mode chỉ cảnh báo file ngoài manifest; Strict mode đánh dấu bundle FAILED.")
        row.addWidget(self.strict_mode)
        export_json = QPushButton("Xuất JSON")
        export_json.clicked.connect(self._export_json)
        row.addWidget(export_json)
        export_html = QPushButton("Xuất HTML")
        export_html.clicked.connect(self._export_html)
        row.addWidget(export_html)
        layout.addLayout(row)

        self.status = QLabel("Chưa chọn bundle.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Payload", "Expected SHA-256", "Actual SHA-256", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 2)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlainText("Module chỉ đọc file ZIP được chọn. Không giải nén vào project và không nhập dữ liệu vào DVS AI.")
        layout.addWidget(self.detail, 1)

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Mở Independent Audit Bundle", "", "ZIP (*.zip)")
        if not path:
            return
        self.bundle_path = path
        self.report = None
        self.table.setRowCount(0)
        self.status.setText(f"Đã chọn: {path}")
        self.detail.setPlainText("Nhấn Xác minh để kiểm tra manifest, payload checksum và Frozen Decision Engine MD5.")

    def _verify(self):
        if not self.bundle_path:
            QMessageBox.information(self, "Audit Verification", "Hãy chọn một bundle ZIP trước.")
            return
        self.service = IndependentAuditBundleVerifier(strict=self.strict_mode.isChecked())
        self.report = self.service.verify(self.bundle_path)
        self._render()
        if self.report["valid"]:
            QMessageBox.information(self, "Audit Verification", "VERIFIED: manifest, payload và Frozen Engine MD5 đều PASS.")
        else:
            QMessageBox.warning(self, "Audit Verification", "FAILED: bundle không vượt qua xác minh. Xem chi tiết trong màn hình.")

    def _render(self):
        assert self.report is not None
        report = self.report
        self.status.setText(
            f"{report['status']} · Manifest {report['manifest_status']} · Engine {report['engine_status']} · Payload {report['payload_status']}"
        )
        payloads = report.get("payloads", [])
        self.table.setRowCount(len(payloads))
        for row, payload in enumerate(payloads):
            values = [payload.get("path"), payload.get("expected_sha256"), payload.get("actual_sha256"), payload.get("status")]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem("" if value is None else str(value)))
        self.detail.setPlainText(json.dumps(report, ensure_ascii=False, indent=2))

    def _export_json(self):
        if not self.report:
            QMessageBox.information(self, "Audit Verification", "Chưa có kết quả xác minh để xuất.")
            return
        default = f"verification_report_{Path(self.bundle_path or 'bundle').stem}.json"
        path, _ = QFileDialog.getSaveFileName(self, "Xuất Verification Report", default, "JSON (*.json)")
        if path:
            saved = self.service.export_json(self.report, path)
            QMessageBox.information(self, "Audit Verification", f"Đã xuất:\n{saved}")

    def _export_html(self):
        if not self.report:
            QMessageBox.information(self, "Audit Verification", "Chưa có kết quả xác minh để xuất.")
            return
        default = f"verification_report_{Path(self.bundle_path or 'bundle').stem}.html"
        path, _ = QFileDialog.getSaveFileName(self, "Xuất Verification Report", default, "HTML (*.html)")
        if path:
            saved = self.service.export_html(self.report, path)
            QMessageBox.information(self, "Audit Verification", f"Đã xuất:\n{saved}")
