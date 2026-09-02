from __future__ import annotations
import json
from PySide6.QtCore import QObject,QThread,Signal,Slot
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableWidget,QTableWidgetItem,QTextEdit,QFileDialog,QMessageBox
from dvs_ai.services.governance_incident_ledger import GovernanceIncidentLedgerService

class _Worker(QObject):
    ready=Signal(object); failed=Signal(str)
    def __init__(self,w,r,l): super().__init__(); self.s=GovernanceIncidentLedgerService(w,r,l)
    @Slot() 
    def refresh(self):
        try: self.ready.emit({'scan':None,'incidents':self.s.list_incidents(True)})
        except Exception as e: self.failed.emit(f'{type(e).__name__}: {e}')
    @Slot()
    def scan(self):
        try: self.ready.emit({'scan':self.s.scan(),'incidents':self.s.list_incidents(True)})
        except Exception as e: self.failed.emit(f'{type(e).__name__}: {e}')

class GovernanceIncidentLedgerWidget(QWidget):
    request_refresh=Signal(); request_scan=Signal()
    def __init__(self,workspace='data/research_workspace.db',review_db='data/research_reviews.db',ledger='data/research_governance_ledger.db',parent=None):
        super().__init__(parent); self.workspace=workspace; self.review_db=review_db; self.ledger=ledger; self.thread=QThread(self); self.worker=_Worker(workspace,review_db,ledger); self.worker.moveToThread(self.thread); self.request_refresh.connect(self.worker.refresh); self.request_scan.connect(self.worker.scan); self.worker.ready.connect(self._render); self.worker.failed.connect(self._show_error); self._build(); self.thread.start(); self.request_refresh.emit()
    def _build(self):
        l=QVBoxLayout(self); l.addWidget(QLabel('Governance Incident & Compliance Exceptions Ledger · deterministic · no automatic remediation'))
        row=QHBoxLayout();
        for text,fn in [('Làm mới',self.request_refresh.emit),('Quét exceptions',self.request_scan.emit),('Xuất JSON',self._json),('Xuất HTML',self._html)]: b=QPushButton(text); b.clicked.connect(fn); row.addWidget(b)
        l.addLayout(row); self.summary=QLabel('Chưa tải'); l.addWidget(self.summary); self.table=QTableWidget(0,8); self.table.setHorizontalHeaderLabels(['Severity','Code','Target type','Target ID','State','First seen','Last seen','Occurrences']); self.table.itemSelectionChanged.connect(self._detail); l.addWidget(self.table,1); self.details=QTextEdit(); self.details.setReadOnly(True); self.details.setMaximumHeight(170); l.addWidget(self.details); self.rows=[]
    @Slot(object)
    def _render(self,p):
        self.rows=p['incidents']; active=[x for x in self.rows if x['state']!='RESOLVED']; self.summary.setText(f"Active {len(active)} · Total {len(self.rows)}" + (f" · Scan detected {p['scan']['detected']}" if p['scan'] else ''))
        self.table.setRowCount(len(self.rows))
        for i,x in enumerate(self.rows):
            vals=[x['severity'],x['code'],x['target_type'],x['target_id'],x['state'],x['first_seen'],x['last_seen'],x['occurrence_count']]
            for j,v in enumerate(vals): self.table.setItem(i,j,QTableWidgetItem(str(v)))
        if self.rows: self.table.selectRow(0)
    def _detail(self):
        r=self.table.currentRow(); self.details.setPlainText(json.dumps(self.rows[r] if 0<=r<len(self.rows) else {},ensure_ascii=False,indent=2))
    def _json(self):
        p,_=QFileDialog.getSaveFileName(self,'Xuất JSON','governance_incidents.json','JSON (*.json)');
        if p: GovernanceIncidentLedgerService(self.workspace,self.review_db,self.ledger).export_json(p)
    def _html(self):
        p,_=QFileDialog.getSaveFileName(self,'Xuất HTML','governance_incidents.html','HTML (*.html)');
        if p: GovernanceIncidentLedgerService(self.workspace,self.review_db,self.ledger).export_html(p)
    @Slot(str)
    def _show_error(self, message):
        QMessageBox.warning(self, 'Governance Ledger', message)
    def close(self,timeout_ms=5000): self.thread.quit(); self.thread.wait(timeout_ms)
