from __future__ import annotations

import json
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget

from dvs_ai.services.research_governance_audit_bundle import ResearchGovernanceAuditBundleService


class ResearchGovernanceAuditBundleWidget(QWidget):
    def __init__(self, workspace='data/research_workspace.db', reviews='data/research_reviews.db', ledger='data/research_governance_ledger.db', parent=None):
        super().__init__(parent)
        self.service = ResearchGovernanceAuditBundleService(workspace, reviews, ledger)
        layout = QVBoxLayout(self)
        title = QLabel('Independent Audit Bundle · provenance · reviews · incidents · alerts · checksums')
        title.setWordWrap(True); layout.addWidget(title)
        row = QHBoxLayout()
        build = QPushButton('Tạo Audit Bundle'); build.clicked.connect(self._build); row.addWidget(build)
        verify = QPushButton('Kiểm tra Bundle'); verify.clicked.connect(self._verify); row.addWidget(verify)
        layout.addLayout(row)
        self.detail = QTextEdit(); self.detail.setReadOnly(True); layout.addWidget(self.detail)
        self.detail.setPlainText('Nguồn dữ liệu chỉ được đọc. Bundle có manifest SHA-256 và verify_bundle.py độc lập.')

    def _build(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Tạo Independent Audit Bundle', 'DVS_AI_Research_Governance_Audit_Bundle.zip', 'ZIP (*.zip)')
        if not path:
            return
        try:
            result = self.service.export_bundle(path)
            self.detail.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
            QMessageBox.information(self, 'Audit Bundle', f"Đã tạo bundle\nSHA-256: {result['sha256']}")
        except Exception as exc:
            QMessageBox.warning(self, 'Audit Bundle', f'{type(exc).__name__}: {exc}')

    def _verify(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Kiểm tra Audit Bundle', '', 'ZIP (*.zip)')
        if not path:
            return
        try:
            result = self.service.verify_bundle(path)
            self.detail.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
            if result['valid']:
                QMessageBox.information(self, 'Audit Bundle', 'Bundle hợp lệ; toàn bộ payload checksum PASS.')
            else:
                QMessageBox.warning(self, 'Audit Bundle', 'Bundle không hợp lệ.')
        except Exception as exc:
            QMessageBox.warning(self, 'Audit Bundle', f'{type(exc).__name__}: {exc}')
