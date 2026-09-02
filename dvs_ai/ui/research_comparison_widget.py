from __future__ import annotations
import json
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QFileDialog
from dvs_ai.services.research_reproducibility import ExperimentComparisonService

class _Worker(QObject):
    ready = Signal(object); failed = Signal(str)
    def __init__(self, workspace): super().__init__(); self.service = ExperimentComparisonService(workspace)
    @Slot(str)
    def compare(self, text):
        try:
            ids = [x.strip() for x in text.replace(',', '\n').splitlines() if x.strip()]
            report = self.service.compare(ids)
            self.ready.emit({'rows': self.service.list_comparisons(), 'report': report})
        except Exception as e: self.failed.emit(f'{type(e).__name__}: {e}')
    @Slot()
    def load(self): self.ready.emit({'rows': self.service.list_comparisons(), 'report': None})

class ResearchComparisonWidget(QWidget):
    compare_request = Signal(str); load_request = Signal()
    def __init__(self, workspace='data/research_workspace.db', parent=None):
        super().__init__(parent); self.current_report = None
        self.thread = QThread(self); self.worker = _Worker(workspace); self.worker.moveToThread(self.thread)
        self.compare_request.connect(self.worker.compare); self.load_request.connect(self.worker.load)
        self.worker.ready.connect(self.render); self.worker.failed.connect(self._show_error)
        self._build(); self.thread.start(); self.load_request.emit()
    def _build(self):
        l=QVBoxLayout(self); l.addWidget(QLabel('Experiment Comparison · reproducibility verification · read-only · no tuning'))
        self.ids=QTextEdit(); self.ids.setPlaceholderText('Dán ít nhất 2 Experiment ID, mỗi ID một dòng'); self.ids.setMaximumHeight(90); l.addWidget(self.ids)
        h=QHBoxLayout(); b=QPushButton('So sánh runs'); b.clicked.connect(lambda: self.compare_request.emit(self.ids.toPlainText())); h.addWidget(b)
        j=QPushButton('Xuất JSON'); j.clicked.connect(self._export_json); h.addWidget(j); x=QPushButton('Xuất HTML'); x.clicked.connect(self._export_html); h.addWidget(x); l.addLayout(h)
        self.table=QTableWidget(0,5); self.table.setHorizontalHeaderLabels(['Comparison ID','Created','Status','Verdict','Report SHA256']); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); l.addWidget(self.table)
        self.detail=QTextEdit(); self.detail.setReadOnly(True); l.addWidget(self.detail)
    @Slot(object)
    def render(self,p):
        rows=p.get('rows',[]); self.table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            for j,k in enumerate(['comparison_id','created_at','status','verdict','report_sha256']): self.table.setItem(i,j,QTableWidgetItem(str(r.get(k,''))))
        if p.get('report'): self.current_report=p['report']; self.detail.setPlainText(json.dumps(self.current_report,ensure_ascii=False,indent=2))
    @Slot(str)
    def _show_error(self, message):
        QMessageBox.warning(self, 'Reproducibility', message)
    def _export_json(self):
        if not self.current_report: return
        path,_=QFileDialog.getSaveFileName(self,'Xuất JSON','experiment_comparison.json','JSON (*.json)')
        if path: ExperimentComparisonService().export_json(self.current_report,path)
    def _export_html(self):
        if not self.current_report: return
        path,_=QFileDialog.getSaveFileName(self,'Xuất HTML','experiment_comparison.html','HTML (*.html)')
        if path: ExperimentComparisonService().export_html(self.current_report,path)
    def close(self,timeout_ms=5000): self.thread.quit(); self.thread.wait(timeout_ms)
