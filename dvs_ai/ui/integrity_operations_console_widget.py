from __future__ import annotations
import json
from typing import Any
from PySide6.QtCore import QObject,QThread,Signal,Slot
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QLineEdit,QTableWidget,QTableWidgetItem,QHeaderView,QTextEdit,QFileDialog,QMessageBox,QSplitter
from dvs_ai.services.integrity_operations_console import IntegrityOperationsConsoleService
class _Worker(QObject):
 ready=Signal(object); failed=Signal(str)
 def __init__(self,s,l): super().__init__(); self.service=IntegrityOperationsConsoleService(s,l)
 @Slot(bool)
 def load(self,capture=False):
  try:self.ready.emit(self.service.snapshot(capture))
  except Exception as e:self.failed.emit(f'{type(e).__name__}: {e}')
class IntegrityOperationsConsoleWidget(QWidget):
 request=Signal(bool)
 def __init__(self,source_db_path,ledger_path,parent=None):
  super().__init__(parent); self.payload={}; self.thread=QThread(self); self.worker=_Worker(source_db_path,ledger_path); self.worker.moveToThread(self.thread); self.request.connect(self.worker.load); self.worker.ready.connect(self.render); self.worker.failed.connect(self._show_error); self.build(); self.thread.start(); self.request.emit(False)
 @Slot(str)
 def _show_error(self,message):
  QMessageBox.warning(self,'Integrity Operations',message)
 def build(self):
  l=QVBoxLayout(self); top=QHBoxLayout(); self.banner=QLabel('Integrity Operations: loading…'); top.addWidget(self.banner); top.addStretch();
  for text,cap in [('Tải ledger',False),('Quét & ghi snapshot',True)]: b=QPushButton(text); b.clicked.connect(lambda _=False,x=cap:self.request.emit(x)); top.addWidget(b)
  ej=QPushButton('Xuất JSON'); ej.clicked.connect(lambda:self.export('json')); top.addWidget(ej); eh=QPushButton('Xuất HTML'); eh.clicked.connect(lambda:self.export('html')); top.addWidget(eh); l.addLayout(top)
  f=QHBoxLayout(); self.level=QComboBox(); self.level.addItems(['ALL','URGENT','ALERT','WATCH','NOTICE','NONE']); self.sev=QComboBox(); self.sev.addItems(['ALL','CRITICAL','ERROR','WARNING','INFO']); self.state=QComboBox(); self.state.addItems(['ALL','OPEN','RESOLVED']); self.search=QLineEdit(); self.search.setPlaceholderText('Code, entity hoặc ID…');
  for w in [self.level,self.sev,self.state,self.search]: f.addWidget(w); (w.currentTextChanged if isinstance(w,QComboBox) else w.textChanged).connect(self.apply_filters)
  l.addLayout(f); split=QSplitter(); self.table=QTableWidget(0,9); self.table.setHorizontalHeaderLabels(['Alert','Severity','Code','Entity','ID','State','Age(s)','Occurrences','Recurrences']); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); self.table.itemSelectionChanged.connect(self.details); split.addWidget(self.table); self.detail=QTextEdit(); self.detail.setReadOnly(True); split.addWidget(self.detail); split.setSizes([850,450]); l.addWidget(split,1)
 def apply_filters(self):
  rows=self.payload.get('incidents',[]); q=self.search.text().lower().strip(); out=[]
  for r in rows:
   if self.level.currentText()!='ALL' and r.get('alert_level')!=self.level.currentText(): continue
   if self.sev.currentText()!='ALL' and r.get('severity')!=self.sev.currentText(): continue
   if self.state.currentText()!='ALL' and r.get('state')!=self.state.currentText(): continue
   if q and q not in ' '.join(str(r.get(k,'')) for k in ('code','entity','entity_id','detail')).lower(): continue
   out.append(r)
  self.filtered=out; self.table.setRowCount(len(out))
  for i,r in enumerate(out):
   for j,v in enumerate([r.get('alert_level'),r.get('severity'),r.get('code'),r.get('entity'),r.get('entity_id'),r.get('state'),r.get('age_seconds',0),r.get('occurrence_count',0),r.get('recurrence_count',0)]): self.table.setItem(i,j,QTableWidgetItem(str(v)))
 def details(self):
  i=self.table.currentRow()
  if i<0 or i>=len(getattr(self,'filtered',[])): return
  r=self.filtered[i]; self.detail.setPlainText(json.dumps({'incident':{k:v for k,v in r.items() if k!='manual_guidance'},'manual_guidance':r.get('manual_guidance',[]),'safety':'Preserve evidence. This console performs no repair.'},ensure_ascii=False,indent=2))
 @Slot(object)
 def render(self,p): self.payload=p; c=p.get('level_counts',{}); self.banner.setText(f"Integrity Operations: {p.get('alert_status')} · {p.get('incident_count')} incidents · U {c.get('URGENT',0)} / A {c.get('ALERT',0)} / W {c.get('WATCH',0)} / N {c.get('NOTICE',0)}"); self.apply_filters()
 def export(self,kind):
  if not self.payload:return
  path,_=QFileDialog.getSaveFileName(self,'Xuất báo cáo',f'integrity_operations_report.{kind}',f'{kind.upper()} (*.{kind})')
  if not path:return
  try:
   svc=IntegrityOperationsConsoleService.__new__(IntegrityOperationsConsoleService); (svc.export_json if kind=='json' else svc.export_html)(self.payload,path)
  except Exception as e: QMessageBox.warning(self,'Xuất báo cáo',str(e))
 def close(self,timeout_ms=5000): self.thread.quit(); self.thread.wait(timeout_ms)
