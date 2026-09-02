from __future__ import annotations
import json
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QFileDialog
from dvs_ai.services.research_cohort_service import ResearchCohortService

class _Worker(QObject):
    ready = Signal(object); failed = Signal(str)
    def __init__(self, source, workspace): super().__init__(); self.service = ResearchCohortService(source, workspace)
    @Slot(str, str, str)
    def create_run(self, name, objective, text):
        try:
            ids=[x.strip() for x in text.replace(',', '\n').splitlines() if x.strip()]
            cid=self.service.create_cohort(name, objective, ids)
            summary=self.service.run_cohort(cid)
            self.ready.emit({'rows':self.service.list_cohorts(),'summary':summary})
        except Exception as e: self.failed.emit(f'{type(e).__name__}: {e}')
    @Slot()
    def load(self):
        try:
            self.ready.emit({'rows': self.service.list_cohorts(), 'summary': None})
        except Exception as e:
            self.failed.emit(f'{type(e).__name__}: {e}')

class ResearchCohortWidget(QWidget):
    create_request=Signal(str,str,str); load_request=Signal()
    def __init__(self, source, workspace='data/research_workspace.db', parent=None):
        super().__init__(parent); self.current_summary=None; self.source=source; self.workspace=workspace
        self.thread=QThread(self); self.worker=_Worker(source,workspace); self.worker.moveToThread(self.thread)
        self.create_request.connect(self.worker.create_run); self.load_request.connect(self.worker.load)
        self.worker.ready.connect(self.render); self.worker.failed.connect(self._show_error)
        self._build(); self.thread.start(); self.load_request.emit()
    def _build(self):
        l=QVBoxLayout(self); l.addWidget(QLabel('Experiment Cohort · controlled batch study · descriptive only · no tuning'))
        self.name=QLineEdit(); self.name.setPlaceholderText('Tên cohort'); l.addWidget(self.name)
        self.objective=QLineEdit(); self.objective.setPlaceholderText('Mục tiêu nghiên cứu'); l.addWidget(self.objective)
        self.ids=QTextEdit(); self.ids.setPlaceholderText('Dán ít nhất 2 Experiment ID, mỗi ID một dòng'); self.ids.setMaximumHeight(90); l.addWidget(self.ids)
        h=QHBoxLayout(); b=QPushButton('Tạo và chạy cohort'); b.clicked.connect(self._submit_create); h.addWidget(b)
        j=QPushButton('Xuất JSON'); j.clicked.connect(self._export_json); h.addWidget(j); x=QPushButton('Xuất HTML'); x.clicked.connect(self._export_html); h.addWidget(x); l.addLayout(h)
        self.table=QTableWidget(0,6); self.table.setHorizontalHeaderLabels(['Cohort ID','Name','Created','Status','Config SHA256','Summary SHA256']); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); l.addWidget(self.table)
        self.detail=QTextEdit(); self.detail.setReadOnly(True); l.addWidget(self.detail)
    @Slot(object)
    def render(self,p):
        rows=p.get('rows',[]); self.table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            for j,k in enumerate(['cohort_id','name','created_at','status','configuration_sha256','summary_sha256']): self.table.setItem(i,j,QTableWidgetItem(str(r.get(k,''))))
        if p.get('summary'): self.current_summary=p['summary']; self.detail.setPlainText(json.dumps(self.current_summary,ensure_ascii=False,indent=2))
    @Slot()
    def _submit_create(self):
        ids = [x.strip() for x in self.ids.toPlainText().replace(',', '\n').splitlines() if x.strip()]
        if len(ids) < 2:
            QMessageBox.information(self, 'Research Cohort', 'Cần nhập ít nhất 2 Experiment ID.')
            return
        self.create_request.emit(self.name.text(), self.objective.text(), '\n'.join(ids))

    @Slot(str)
    def _show_error(self, message):
        QMessageBox.warning(self, 'Research Cohort', message)
    def _export_json(self):
        if not self.current_summary:return
        path,_=QFileDialog.getSaveFileName(self,'Xuất JSON','research_cohort.json','JSON (*.json)')
        if path: ResearchCohortService(self.source,self.workspace).export_json(self.current_summary,path)
    def _export_html(self):
        if not self.current_summary:return
        path,_=QFileDialog.getSaveFileName(self,'Xuất HTML','research_cohort.html','HTML (*.html)')
        if path: ResearchCohortService(self.source,self.workspace).export_html(self.current_summary,path)
    def shutdown(self, timeout_ms=5000):
        if self.thread.isRunning():
            self.thread.quit(); self.thread.wait(timeout_ms)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
