from __future__ import annotations
import json
from PySide6.QtCore import QObject,QThread,Signal,Slot
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableWidget,QTableWidgetItem,QTextEdit,QFileDialog,QMessageBox
from dvs_ai.services.governance_alert_policy import GovernanceAlertPolicyService

class _Worker(QObject):
    ready=Signal(object); failed=Signal(str)
    def __init__(self,w,r,l): super().__init__(); self.s=GovernanceAlertPolicyService(w,r,l)
    @Slot()
    def evaluate(self):
        try: self.ready.emit(self.s.evaluate(False))
        except Exception as e: self.failed.emit(f'{type(e).__name__}: {e}')
    @Slot()
    def scan(self):
        try: self.ready.emit(self.s.evaluate(True))
        except Exception as e: self.failed.emit(f'{type(e).__name__}: {e}')

class GovernanceComplianceOperationsWidget(QWidget):
    request_evaluate=Signal(); request_scan=Signal()
    def __init__(self,workspace='data/research_workspace.db',reviews='data/research_reviews.db',ledger='data/research_governance_ledger.db',parent=None):
        super().__init__(parent); self.paths=(workspace,reviews,ledger); self.rows=[]
        self.thread=QThread(self); self.worker=_Worker(*self.paths); self.worker.moveToThread(self.thread)
        self.request_evaluate.connect(self.worker.evaluate); self.request_scan.connect(self.worker.scan)
        self.worker.ready.connect(self._render); self.worker.failed.connect(self._show_error)
        self._build(); self.thread.start(); self.request_evaluate.emit()
    def _build(self):
        l=QVBoxLayout(self); l.addWidget(QLabel('Governance Alert Policy & Compliance Operations · deterministic · read-only · no automatic remediation'))
        row=QHBoxLayout()
        for text,fn in [('Evaluate Ledger',self.request_evaluate.emit),('Scan & Alert',self.request_scan.emit),('Xuất JSON',self._json),('Xuất HTML',self._html)]:
            b=QPushButton(text); b.clicked.connect(fn); row.addWidget(b)
        l.addLayout(row); self.summary=QLabel('Chưa tải'); l.addWidget(self.summary)
        self.table=QTableWidget(0,8); self.table.setHorizontalHeaderLabels(['Alert','Severity','Code','Target type','Target ID','State','Occurrences','Last changed']); self.table.itemSelectionChanged.connect(self._detail); l.addWidget(self.table,1)
        self.details=QTextEdit(); self.details.setReadOnly(True); self.details.setMaximumHeight(190); l.addWidget(self.details)
    @Slot(object)
    def _render(self,p):
        s=p['snapshot']; self.rows=s['incidents']; c=s['level_counts']; self.summary.setText(f"Status {s['status']} · U {c.get('URGENT',0)} / A {c.get('ALERT',0)} / W {c.get('WATCH',0)} / N {c.get('NOTICE',0)} · Policy {s['policy_version']}")
        self.table.setRowCount(len(self.rows))
        for i,x in enumerate(self.rows):
            vals=[x['alert_level'],x.get('severity',''),x.get('code',''),x.get('target_type',''),x.get('target_id',''),x.get('state',''),x.get('occurrence_count',0),x.get('last_changed','')]
            for j,v in enumerate(vals): self.table.setItem(i,j,QTableWidgetItem(str(v)))
        if self.rows: self.table.selectRow(0)
        urgent=[x for x in p.get('changes',[]) if x['to']=='URGENT']
        if urgent: QMessageBox.warning(self,'URGENT governance alert','Read-only alert only. No repair or Decision Engine change was performed.')
    def _detail(self):
        r=self.table.currentRow(); self.details.setPlainText(json.dumps(self.rows[r] if 0<=r<len(self.rows) else {},ensure_ascii=False,indent=2))
    def _json(self):
        p,_=QFileDialog.getSaveFileName(self,'Xuất JSON','compliance_operations.json','JSON (*.json)')
        if p: GovernanceAlertPolicyService(*self.paths).export_json(p)
    def _html(self):
        p,_=QFileDialog.getSaveFileName(self,'Xuất HTML','compliance_operations.html','HTML (*.html)')
        if p: GovernanceAlertPolicyService(*self.paths).export_html(p)
    @Slot(str)
    def _show_error(self, message):
        QMessageBox.warning(self, 'Compliance Operations', message)
    def close(self,timeout_ms=5000): self.thread.quit(); self.thread.wait(timeout_ms)
