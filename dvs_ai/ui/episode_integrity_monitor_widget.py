from __future__ import annotations
import json
from typing import Any
from PySide6.QtCore import QObject,QThread,Signal,Slot
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableWidget,QTableWidgetItem,QHeaderView,QTextEdit,QMessageBox
from dvs_ai.services.episode_integrity_monitor import EpisodeIntegrityMonitor

class _Worker(QObject):
    ready=Signal(object); failed=Signal(str)
    def __init__(self,db_path:str): super().__init__(); self.service=EpisodeIntegrityMonitor(db_path)
    @Slot()
    def load(self):
        try:self.ready.emit(self.service.snapshot())
        except Exception as exc:self.failed.emit(f"{type(exc).__name__}: {exc}")

class EpisodeIntegrityMonitorWidget(QWidget):
    request_refresh=Signal()
    DISPLAY_LIMIT=500
    def __init__(self,db_path:str,parent=None):
        super().__init__(parent); self._thread=QThread(self); self._worker=_Worker(db_path); self._worker.moveToThread(self._thread)
        self.request_refresh.connect(self._worker.load); self._worker.ready.connect(self._render); self._worker.failed.connect(self._fail)
        self._build(); self._thread.start(); self.refresh()
    def _build(self):
        lay=QVBoxLayout(self); top=QHBoxLayout(); self.status=QLabel("Integrity: loading…"); top.addWidget(self.status); top.addStretch(1)
        b=QPushButton("Làm mới"); b.clicked.connect(self.refresh); top.addWidget(b); lay.addLayout(top)
        self.summary=QTextEdit(); self.summary.setReadOnly(True); self.summary.setMaximumHeight(120); lay.addWidget(self.summary)
        self.table=QTableWidget(0,5); self.table.setHorizontalHeaderLabels(["Severity","Code","Entity","ID","Detail"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); self.table.horizontalHeader().setStretchLastSection(True); lay.addWidget(self.table,1)
    @Slot()
    def refresh(self): self.request_refresh.emit()
    @Slot(object)
    def _render(self,p:dict[str,Any]):
        self.status.setText(f"Integrity: {p.get('status')} · Issues: {p.get('issue_count',0)}")
        self.summary.setPlainText(json.dumps({"generated_at":p.get("generated_at"),"severity_counts":p.get("severity_counts",{}),"code_counts":p.get("code_counts",{}),"notes":p.get("notes",[])},ensure_ascii=False,indent=2))
        all_rows=p.get("issues",[])
        rows=all_rows[-self.DISPLAY_LIMIT:]
        self.status.setText(f"Integrity: {p.get('status')} · Issues: {p.get('issue_count',0)} · Displayed: {len(rows)}/{len(all_rows)}")
        self.table.clearContents(); self.table.setRowCount(len(rows))
        for r,it in enumerate(rows):
            for c,k in enumerate(("severity","code","entity","entity_id","detail")): self.table.setItem(r,c,QTableWidgetItem(str(it.get(k,""))))
    @Slot(str)
    def _fail(self,m): QMessageBox.warning(self,"Episode Integrity",m)
    def close(self,timeout_ms:int=5000):
        if self._thread.isRunning(): self._thread.quit(); self._thread.wait(timeout_ms)
