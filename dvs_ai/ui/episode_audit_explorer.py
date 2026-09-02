from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,
    QSplitter,QTableWidget,QTableWidgetItem,QHeaderView,QTextEdit,QTabWidget,QMessageBox)

from dvs_ai.services.episode_audit_service import EpisodeAuditService


class _AuditWorker(QObject):
    episodes_ready = Signal(object)
    detail_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, db_path: str) -> None:
        super().__init__(); self.service = EpisodeAuditService(db_path)

    @Slot(str)
    def load_episodes(self, symbol: str = "") -> None:
        try: self.episodes_ready.emit(self.service.list_episodes(symbol=symbol or None))
        except Exception as exc: self.failed.emit(f"{type(exc).__name__}: {exc}")

    @Slot(str)
    def load_detail(self, episode_id: str) -> None:
        try: self.detail_ready.emit(self.service.episode_detail(episode_id))
        except Exception as exc: self.failed.emit(f"{type(exc).__name__}: {exc}")


class EpisodeAuditExplorer(QWidget):
    request_episodes = Signal(str)
    request_detail = Signal(str)

    def __init__(self, db_path: str, parent=None) -> None:
        super().__init__(parent); self.db_path=db_path; self._detail={}
        self._thread=QThread(self); self._worker=_AuditWorker(db_path); self._worker.moveToThread(self._thread)
        self.request_episodes.connect(self._worker.load_episodes); self.request_detail.connect(self._worker.load_detail)
        self._worker.episodes_ready.connect(self._render_episodes); self._worker.detail_ready.connect(self._render_detail); self._worker.failed.connect(self._fail)
        self._build(); self._thread.start(); self.refresh()

    def _build(self) -> None:
        layout=QVBoxLayout(self)
        top=QHBoxLayout(); top.addWidget(QLabel("Episode Audit Explorer · READ-ONLY")); top.addStretch(1)
        self.search=QLineEdit(); self.search.setPlaceholderText("Lọc symbol..."); top.addWidget(self.search)
        btn=QPushButton("Làm mới"); btn.clicked.connect(self.refresh); top.addWidget(btn); layout.addLayout(top)
        split=QSplitter(); layout.addWidget(split,1)
        self.episodes=QTableWidget(0,8); self.episodes.setHorizontalHeaderLabels(["Last seen","Symbol","Dir","Evaluations","Class","Candidate","Outcome","Episode ID"])
        self.episodes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); self.episodes.horizontalHeader().setStretchLastSection(True)
        self.episodes.itemSelectionChanged.connect(self._selected); split.addWidget(self.episodes)
        right=QTabWidget(); split.addWidget(right); split.setSizes([600,900])
        self.summary=QTextEdit(); self.summary.setReadOnly(True); right.addTab(self.summary,"Episode / Plan")
        self.evals=QTableWidget(0,10); self.evals.setHorizontalHeaderLabels(["#","Time","Entry","Confidence","Opportunity","Trend","Smart Money","Risk","Gates","Evaluation ID"]); self.evals.horizontalHeader().setStretchLastSection(True); right.addTab(self.evals,"Evaluations")
        self.trace=QTextEdit(); self.trace.setReadOnly(True); self.evals.itemSelectionChanged.connect(self._eval_selected); right.addTab(self.trace,"Diagnostic Trace")
        self.timeline=QTableWidget(0,3); self.timeline.setHorizontalHeaderLabels(["Time","Event","Detail"]); self.timeline.horizontalHeader().setStretchLastSection(True); right.addTab(self.timeline,"Outcome Timeline")

    @Slot()
    def refresh(self) -> None: self.request_episodes.emit(self.search.text().strip())

    @Slot(object)
    def _render_episodes(self, rows: list[dict[str,Any]]) -> None:
        self.episodes.setRowCount(len(rows))
        for r,item in enumerate(rows):
            vals=(item.get("last_seen_at"),item.get("symbol"),item.get("direction"),item.get("evaluation_count"),item.get("episode_class") or "—",item.get("candidate_status") or "—",item.get("outcome_status") or "—",item.get("setup_episode_id"))
            for c,v in enumerate(vals): self.episodes.setItem(r,c,QTableWidgetItem(str(v)))
        if rows: self.episodes.selectRow(0)

    def _selected(self) -> None:
        row=self.episodes.currentRow()
        if row>=0 and self.episodes.item(row,7): self.request_detail.emit(self.episodes.item(row,7).text())

    @Slot(object)
    def _render_detail(self, detail: dict[str,Any]) -> None:
        self._detail=detail; ep=detail.get("episode") or {}; cand=detail.get("candidate"); out=detail.get("outcome")
        self.summary.setPlainText(json.dumps({"episode":ep,"candidate":cand,"outcome":out},ensure_ascii=False,indent=2,default=str))
        rows=detail.get("evaluations",[]); self.evals.setRowCount(len(rows))
        for r,item in enumerate(rows):
            tr=item.get("trace") or {}; scores=tr.get("scores",tr)
            vals=(item.get("sequence_number"),item.get("evaluated_at"),item.get("entry_score"),item.get("confidence"),item.get("opportunity_score"),scores.get("directional_trend",scores.get("trend")),scores.get("smart_money_probability",scores.get("smart_money")),scores.get("risk_score",scores.get("risk")),", ".join(item.get("gate_set") or []),item.get("evaluation_id"))
            for c,v in enumerate(vals): self.evals.setItem(r,c,QTableWidgetItem("—" if v is None else str(v)))
        if rows: self.evals.selectRow(0)
        tl=detail.get("timeline",[]); self.timeline.setRowCount(len(tl))
        for r,item in enumerate(tl):
            for c,key in enumerate(("time","kind","detail")): self.timeline.setItem(r,c,QTableWidgetItem(str(item.get(key) or "")))

    def _eval_selected(self) -> None:
        row=self.evals.currentRow(); rows=self._detail.get("evaluations",[])
        if 0<=row<len(rows): self.trace.setPlainText(json.dumps(rows[row],ensure_ascii=False,indent=2,default=str))

    @Slot(str)
    def _fail(self,message:str)->None: QMessageBox.warning(self,"Episode Audit",message)

    def close(self, timeout_ms: int = 5000) -> None:
        if self._thread.isRunning(): self._thread.quit(); self._thread.wait(timeout_ms)
