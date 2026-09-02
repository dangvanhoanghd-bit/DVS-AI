from __future__ import annotations

import json
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from dvs_ai.services.research_governance_dashboard import ResearchGovernanceDashboardService


class _Worker(QObject):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, workspace: str, review_db: str):
        super().__init__()
        self.service = ResearchGovernanceDashboardService(workspace, review_db)

    @Slot()
    def refresh(self):
        try:
            self.ready.emit(self.service.analyze())
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')


class ResearchGovernanceDashboardWidget(QWidget):
    request_refresh = Signal()

    def __init__(self, workspace='data/research_workspace.db', review_db='data/research_reviews.db', parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.review_db = review_db
        self.last_report = None
        self.thread = QThread(self)
        self.worker = _Worker(workspace, review_db)
        self.worker.moveToThread(self.thread)
        self.request_refresh.connect(self.worker.refresh)
        self.worker.ready.connect(self._render)
        self.worker.failed.connect(self._show_error)
        self._build()
        self.thread.start()
        self.request_refresh.emit()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Research Governance Dashboard · review coverage · approval status · checksum integrity · read-only'))
        row = QHBoxLayout()
        refresh = QPushButton('Làm mới'); refresh.clicked.connect(self.request_refresh.emit); row.addWidget(refresh)
        export_json = QPushButton('Xuất JSON'); export_json.clicked.connect(self._export_json); row.addWidget(export_json)
        export_html = QPushButton('Xuất HTML'); export_html.clicked.connect(self._export_html); row.addWidget(export_html)
        layout.addLayout(row)
        self.summary = QLabel('Chưa tải dữ liệu'); self.summary.setWordWrap(True); layout.addWidget(self.summary)
        self.states = QTableWidget(0, 2); self.states.setHorizontalHeaderLabels(['Review state', 'Count']); layout.addWidget(self.states)
        self.coverage = QTableWidget(0, 5); self.coverage.setHorizontalHeaderLabels(['Target type', 'Total', 'Reviewed', 'Unreviewed', 'Coverage']); layout.addWidget(self.coverage)
        self.unreviewed = QTableWidget(0, 3); self.unreviewed.setHorizontalHeaderLabels(['Type', 'Target ID', 'Title']); layout.addWidget(self.unreviewed)
        self.workload = QTableWidget(0, 4); self.workload.setHorizontalHeaderLabels(['Reviewer', 'Reviews', 'Annotations', 'Finalized']); layout.addWidget(self.workload)
        self.detail = QTextEdit(); self.detail.setReadOnly(True); self.detail.setMaximumHeight(150); layout.addWidget(self.detail)

    @staticmethod
    def _fill(table, rows):
        table.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                table.setItem(r, c, QTableWidgetItem(str(value)))

    @Slot(object)
    def _render(self, report):
        self.last_report = report; s = report['summary']
        self.summary.setText(
            f"Coverage {s['reviewed_targets']}/{s['total_targets']} ({s['coverage_rate']:.1%}) · "
            f"Approved {s['approved_reviews']} · Checksum integrity {s['checksum_integrity_rate']:.1%} · "
            f"Unreviewed {s['unreviewed_targets']} · Drift {s['checksum_failures']} · Orphan {s['orphan_reviews']}"
        )
        self._fill(self.states, [[k, v] for k, v in sorted(report['state_counts'].items())])
        self._fill(self.coverage, [[k, v['total'], v['reviewed'], v['unreviewed'], f"{v['coverage_rate']:.1%}"] for k, v in sorted(report['type_coverage'].items())])
        self._fill(self.unreviewed, [[x['target_type'], x['target_id'], x.get('title', '')] for x in report['unreviewed_targets']])
        self._fill(self.workload, [[x['reviewer'], x['review_count'], x['annotation_count'], x['finalized_count']] for x in report['reviewer_workload']])
        self.detail.setPlainText(json.dumps({
            'stale_reviews': report['stale_reviews'],
            'orphan_reviews': report['orphan_reviews'],
            'engine_mismatch_reviews': report['engine_mismatch_reviews'],
            'limitations': report['limitations'],
            'report_sha256': report['report_sha256'],
        }, ensure_ascii=False, indent=2))

    @Slot(str)
    def _show_error(self, message):
        QMessageBox.warning(self, 'Research Governance', message)
    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Xuất JSON', 'research_governance.json', 'JSON (*.json)')
        if path: ResearchGovernanceDashboardService(self.workspace, self.review_db).export_json(path)

    def _export_html(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Xuất HTML', 'research_governance.html', 'HTML (*.html)')
        if path: ResearchGovernanceDashboardService(self.workspace, self.review_db).export_html(path)

    def close(self, timeout_ms=5000):
        self.thread.quit(); self.thread.wait(timeout_ms)
