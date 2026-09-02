from __future__ import annotations
import json
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QFileDialog
from dvs_ai.services.research_cohort_diagnostics import ResearchCohortDiagnosticsService

class _Worker(QObject):
    ready = Signal(object); failed = Signal(str)
    def __init__(self, workspace): super().__init__(); self.service = ResearchCohortDiagnosticsService(workspace)
    @Slot(str)
    def analyze(self, text):
        try:
            ids=[x.strip() for x in text.replace(',', '\n').splitlines() if x.strip()]
            self.ready.emit(self.service.analyze(ids or None))
        except Exception as e: self.failed.emit(f'{type(e).__name__}: {e}')

class ResearchCohortDiagnosticsWidget(QWidget):
    analyze_request=Signal(str)
    def __init__(self, workspace='data/research_workspace.db', parent=None):
        super().__init__(parent); self.workspace=workspace; self.current_report=None
        self.thread=QThread(self); self.worker=_Worker(workspace); self.worker.moveToThread(self.thread)
        self.analyze_request.connect(self.worker.analyze); self.worker.ready.connect(self.render)
        self.worker.failed.connect(self._show_error)
        self._build(); self.thread.start()
    def _build(self):
        l=QVBoxLayout(self); l.addWidget(QLabel('Cohort Statistical Diagnostics · cross-study · descriptive only · no tuning'))
        self.ids=QTextEdit(); self.ids.setPlaceholderText('Tùy chọn: dán Cohort ID, mỗi ID một dòng. Để trống để phân tích tất cả cohort.'); self.ids.setMaximumHeight(72); l.addWidget(self.ids)
        h=QHBoxLayout(); b=QPushButton('Phân tích cohort'); b.clicked.connect(lambda:self.analyze_request.emit(self.ids.toPlainText())); h.addWidget(b)
        j=QPushButton('Xuất JSON'); j.clicked.connect(self._export_json); h.addWidget(j)
        x=QPushButton('Xuất HTML'); x.clicked.connect(self._export_html); h.addWidget(x); l.addLayout(h)
        self.summary=QLabel('Chưa tải dữ liệu'); l.addWidget(self.summary)
        self.table=QTableWidget(0,7); self.table.setHorizontalHeaderLabels(['Cohort','Status','Total','Completed','Completion','Snapshots','Distinct results'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); l.addWidget(self.table)
        self.detail=QTextEdit(); self.detail.setReadOnly(True); l.addWidget(self.detail)
    @Slot(object)
    def render(self,r):
        self.current_report=r; self.summary.setText(f"Cohorts {r['cohort_count']} · Experiments {r['total_experiments']} · Mean completion {r['completion_rate_mean']:.1%} · Snapshots {r['unique_snapshot_count']}")
        self.table.setRowCount(len(r['cohorts']))
        for i,c in enumerate(r['cohorts']):
            vals=[c['name'],c['status'],c['total_experiments'],c['completed_experiments'],f"{c['completion_rate']:.1%}",c['snapshot_count'],c['distinct_result_count']]
            for j,v in enumerate(vals): self.table.setItem(i,j,QTableWidgetItem(str(v)))
        self.detail.setPlainText(json.dumps(r,ensure_ascii=False,indent=2))
    @Slot(str)
    def _show_error(self, message):
        QMessageBox.warning(self, 'Cohort Diagnostics', message)
    def _export_json(self):
        if not self.current_report:return
        p,_=QFileDialog.getSaveFileName(self,'Xuất JSON','cohort_diagnostics.json','JSON (*.json)')
        if p: ResearchCohortDiagnosticsService(self.workspace).export_json(self.current_report,p)
    def _export_html(self):
        if not self.current_report:return
        p,_=QFileDialog.getSaveFileName(self,'Xuất HTML','cohort_diagnostics.html','HTML (*.html)')
        if p: ResearchCohortDiagnosticsService(self.workspace).export_html(self.current_report,p)
    def close(self,timeout_ms=5000): self.thread.quit(); self.thread.wait(timeout_ms)
