from __future__ import annotations

import json
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from dvs_ai.services.research_lineage_provenance import ResearchLineageProvenanceService


class _Worker(QObject):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, workspace: str):
        super().__init__()
        self.service = ResearchLineageProvenanceService(workspace)

    @Slot()
    def analyze(self):
        try:
            self.ready.emit(self.service.analyze())
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')


class ResearchLineageProvenanceWidget(QWidget):
    analyze_request = Signal()

    def __init__(self, workspace: str = 'data/research_workspace.db', parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.current_report = None
        self.thread = QThread(self)
        self.worker = _Worker(workspace)
        self.worker.moveToThread(self.thread)
        self.analyze_request.connect(self.worker.analyze)
        self.worker.ready.connect(self.render)
        self.worker.failed.connect(self._show_error)
        self._build()
        self.thread.start()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Research Dataset Lineage & Provenance · read-only · no tuning'))
        buttons = QHBoxLayout()
        analyze = QPushButton('Phân tích lineage')
        analyze.clicked.connect(self.analyze_request.emit)
        buttons.addWidget(analyze)
        export_json = QPushButton('Xuất JSON')
        export_json.clicked.connect(self._export_json)
        buttons.addWidget(export_json)
        export_html = QPushButton('Xuất HTML')
        export_html.clicked.connect(self._export_html)
        buttons.addWidget(export_html)
        layout.addLayout(buttons)
        self.summary = QLabel('Chưa tải dữ liệu')
        layout.addWidget(self.summary)

        self.branches = QTableWidget(0, 3)
        self.branches.setHorizontalHeaderLabels(['Snapshot', 'Experiments', 'Experiment IDs'])
        self.branches.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.branches)

        self.issues = QTableWidget(0, 4)
        self.issues.setHorizontalHeaderLabels(['Severity', 'Code', 'Entity', 'Detail'])
        self.issues.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.issues)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        layout.addWidget(self.detail)

    @Slot(object)
    def render(self, report):
        self.current_report = report
        c = report['counts']
        self.summary.setText(
            f"Snapshots {c['snapshots']} · Experiments {c['experiments']} · "
            f"Comparisons {c['comparisons']} · Cohorts {c['cohorts']} · Issues {c['issues']}"
        )
        self.branches.setRowCount(len(report['branch_points']))
        for row, item in enumerate(report['branch_points']):
            values = [item['snapshot_id'], item['experiment_count'], ', '.join(item['experiment_ids'])]
            for col, value in enumerate(values):
                self.branches.setItem(row, col, QTableWidgetItem(str(value)))
        self.issues.setRowCount(len(report['issues']))
        for row, item in enumerate(report['issues']):
            values = [item['severity'], item['code'], item['entity_id'], item['detail']]
            for col, value in enumerate(values):
                self.issues.setItem(row, col, QTableWidgetItem(str(value)))
        self.detail.setPlainText(json.dumps(report, ensure_ascii=False, indent=2))

    @Slot(str)
    def _show_error(self, message):
        QMessageBox.warning(self, 'Research Lineage', message)
    def _export_json(self):
        if not self.current_report:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Xuất JSON', 'research_lineage.json', 'JSON (*.json)')
        if path:
            ResearchLineageProvenanceService(self.workspace).export_json(self.current_report, path)

    def _export_html(self):
        if not self.current_report:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Xuất HTML', 'research_lineage.html', 'HTML (*.html)')
        if path:
            ResearchLineageProvenanceService(self.workspace).export_html(self.current_report, path)

    def close(self, timeout_ms: int = 5000):
        self.thread.quit()
        self.thread.wait(timeout_ms)
