from __future__ import annotations
import json
from PySide6.QtCore import QObject,QThread,Signal,Slot
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QLineEdit,QTextEdit,QTableWidget,QTableWidgetItem,QHeaderView,QMessageBox
from dvs_ai.services.research_experiment_engine import ResearchExperimentEngine
class _Worker(QObject):
 ready=Signal(object); failed=Signal(str)
 def __init__(self,s,w): super().__init__(); self.engine=ResearchExperimentEngine(s,w)
 @Slot(str,str,str,str)
 def create_run(self,name,hyp,kind,params):
  try:
   p=json.loads(params or '{}'); eid=self.engine.register(name,hyp,kind,p); self.engine.run(eid); self.ready.emit({'rows':self.engine.list_experiments(),'detail':self.engine.get(eid)})
  except Exception as e:self.failed.emit(f'{type(e).__name__}: {e}')
 @Slot()
 def load(self):
  try:self.ready.emit({'rows':self.engine.list_experiments(),'detail':None})
  except Exception as e:self.failed.emit(f'{type(e).__name__}: {e}')
class ResearchExperimentWidget(QWidget):
 run_request=Signal(str,str,str,str); load_request=Signal()
 def __init__(self,source,workspace='data/research_workspace.db',parent=None):
  super().__init__(parent); self.thread=QThread(self); self.worker=_Worker(source,workspace); self.worker.moveToThread(self.thread); self.run_request.connect(self.worker.create_run); self.load_request.connect(self.worker.load); self.worker.ready.connect(self.render); self.worker.failed.connect(self._show_error); self._build(); self.thread.start(); self.load_request.emit()
 @Slot(str)
 def _show_error(self,message):
  QMessageBox.warning(self,'Research Experiment',message)
 def _build(self):
  l=QVBoxLayout(self); l.addWidget(QLabel('Research Experiment Execution · isolated workspace · deterministic allow-list · no Decision Engine calls'))
  f=QHBoxLayout(); self.name=QLineEdit(); self.name.setPlaceholderText('Tên thí nghiệm'); self.kind=QComboBox(); self.kind.addItems(['DATASET_PROFILE','STABILITY_CHECK','GROUP_COMPARISON']); b=QPushButton('Tạo & chạy'); b.clicked.connect(self._run); f.addWidget(self.name); f.addWidget(self.kind); f.addWidget(b); l.addLayout(f)
  self.hyp=QLineEdit(); self.hyp.setPlaceholderText('Giả thuyết / mục tiêu'); l.addWidget(self.hyp); self.params=QTextEdit('{}'); self.params.setMaximumHeight(90); l.addWidget(self.params)
  self.table=QTableWidget(0,6); self.table.setHorizontalHeaderLabels(['ID','Name','Type','Status','Created','Result SHA256']); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); l.addWidget(self.table); self.detail=QTextEdit(); self.detail.setReadOnly(True); l.addWidget(self.detail)
 def _run(self): self.run_request.emit(self.name.text(),self.hyp.text(),self.kind.currentText(),self.params.toPlainText())
 @Slot(object)
 def render(self,p):
  rows=p.get('rows',[]); self.table.setRowCount(len(rows))
  for i,r in enumerate(rows):
   for j,k in enumerate(['experiment_id','name','analysis_type','status','created_at','result_sha256']): self.table.setItem(i,j,QTableWidgetItem(str(r.get(k,''))))
  if p.get('detail'): self.detail.setPlainText(json.dumps(p['detail'],ensure_ascii=False,indent=2))
 def close(self,timeout_ms=5000): self.thread.quit(); self.thread.wait(timeout_ms)
