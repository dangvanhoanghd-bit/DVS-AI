from __future__ import annotations

import json
from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from dvs_ai.services.research_review_workflow import ResearchReviewWorkflowService


class _Worker(QObject):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, workspace: str, review_db: str):
        super().__init__()
        self.service = ResearchReviewWorkflowService(workspace, review_db)

    @Slot(object)
    def execute(self, request):
        try:
            op = request['op']
            if op == 'refresh':
                result = {'op': op, 'reviews': self.service.list_reviews()}
            elif op == 'create':
                rid = self.service.create_review(request['target_type'], request['target_id'], request['actor'], request.get('title', ''))
                result = {'op': op, 'review': self.service.get_review(rid), 'reviews': self.service.list_reviews()}
            elif op == 'annotate':
                self.service.add_annotation(request['review_id'], request['actor'], request['note'], request['category'])
                result = {'op': op, 'review': self.service.get_review(request['review_id']), 'reviews': self.service.list_reviews()}
            elif op == 'transition':
                review = self.service.transition(request['review_id'], request['to_state'], request['actor'], request['reason'])
                result = {'op': op, 'review': review, 'reviews': self.service.list_reviews()}
            else:
                raise ValueError('Unsupported operation')
            self.ready.emit(result)
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')


class ResearchReviewWorkflowWidget(QWidget):
    request = Signal(object)

    def __init__(self, workspace='data/research_workspace.db', review_db='data/research_reviews.db', parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.review_db = review_db
        self.current_review_id = ''
        self.thread = QThread(self)
        self.worker = _Worker(workspace, review_db)
        self.worker.moveToThread(self.thread)
        self.request.connect(self.worker.execute)
        self.worker.ready.connect(self._render)
        self.worker.failed.connect(self._show_error)
        self._build()
        self.thread.start()
        self.request.emit({'op': 'refresh'})

    def _build(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Research Review, Annotation & Approval · isolated review ledger · no result mutation'))
        form = QFormLayout()
        self.target_type = QComboBox(); self.target_type.addItems(['EXPERIMENT', 'COMPARISON', 'COHORT', 'LINEAGE_REPORT', 'COHORT_DIAGNOSTICS'])
        self.target_id = QLineEdit(); self.target_id.setPlaceholderText('Target ID hoặc report SHA-256')
        self.actor = QLineEdit(); self.actor.setPlaceholderText('Reviewer')
        self.title = QLineEdit(); self.title.setPlaceholderText('Tiêu đề tùy chọn')
        form.addRow('Loại đối tượng', self.target_type); form.addRow('Target ID', self.target_id)
        form.addRow('Reviewer', self.actor); form.addRow('Tiêu đề', self.title)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        create = QPushButton('Tạo review'); create.clicked.connect(self._create); buttons.addWidget(create)
        refresh = QPushButton('Làm mới'); refresh.clicked.connect(lambda: self.request.emit({'op': 'refresh'})); buttons.addWidget(refresh)
        export_json = QPushButton('Xuất JSON'); export_json.clicked.connect(self._export_json); buttons.addWidget(export_json)
        export_html = QPushButton('Xuất HTML'); export_html.clicked.connect(self._export_html); buttons.addWidget(export_html)
        layout.addLayout(buttons)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['Review ID', 'Target', 'Title', 'State', 'Reviewer', 'Updated'])
        self.table.itemSelectionChanged.connect(self._select_review)
        layout.addWidget(self.table)

        self.note = QTextEdit(); self.note.setPlaceholderText('Ghi chú reviewer'); self.note.setMaximumHeight(90)
        layout.addWidget(self.note)
        row = QHBoxLayout()
        self.category = QComboBox(); self.category.addItems(['GENERAL', 'METHOD', 'DATA', 'STATISTICS', 'PROVENANCE', 'RISK'])
        row.addWidget(self.category)
        add = QPushButton('Thêm ghi chú'); add.clicked.connect(self._annotate); row.addWidget(add)
        self.next_state = QComboBox(); self.next_state.addItems(['IN_REVIEW', 'CHANGES_REQUESTED', 'APPROVED', 'REJECTED'])
        row.addWidget(self.next_state)
        move = QPushButton('Chuyển trạng thái'); move.clicked.connect(self._transition); row.addWidget(move)
        layout.addLayout(row)
        self.detail = QTextEdit(); self.detail.setReadOnly(True); layout.addWidget(self.detail)

    def _actor(self):
        return self.actor.text().strip() or 'anonymous-reviewer'

    def _create(self):
        self.request.emit({'op': 'create', 'target_type': self.target_type.currentText(), 'target_id': self.target_id.text(), 'actor': self._actor(), 'title': self.title.text()})

    def _annotate(self):
        if self.current_review_id:
            self.request.emit({'op': 'annotate', 'review_id': self.current_review_id, 'actor': self._actor(), 'note': self.note.toPlainText(), 'category': self.category.currentText()})

    def _transition(self):
        if self.current_review_id:
            self.request.emit({'op': 'transition', 'review_id': self.current_review_id, 'actor': self._actor(), 'to_state': self.next_state.currentText(), 'reason': self.note.toPlainText()})

    @Slot(object)
    def _render(self, payload):
        reviews = payload.get('reviews', [])
        self.table.setRowCount(len(reviews))
        for row, item in enumerate(reviews):
            values = [item['review_id'], f"{item['target_type']}:{item['target_id']}", item['title'], item['state'], item['created_by'], item['updated_at']]
            for col, value in enumerate(values): self.table.setItem(row, col, QTableWidgetItem(str(value)))
        if payload.get('review'):
            review = payload['review']; self.current_review_id = review['review_id']
            self.detail.setPlainText(json.dumps(review, ensure_ascii=False, indent=2))
            self.note.clear()

    def _select_review(self):
        row = self.table.currentRow()
        if row >= 0 and self.table.item(row, 0):
            self.current_review_id = self.table.item(row, 0).text()
            try:
                review = ResearchReviewWorkflowService(self.workspace, self.review_db).get_review(self.current_review_id)
                self.detail.setPlainText(json.dumps(review, ensure_ascii=False, indent=2))
            except Exception as exc:
                self.detail.setPlainText(str(exc))

    @Slot(str)
    def _show_error(self, message):
        QMessageBox.warning(self, 'Research Review', message)
    def _export_json(self):
        if not self.current_review_id: return
        path, _ = QFileDialog.getSaveFileName(self, 'Xuất JSON', 'research_review.json', 'JSON (*.json)')
        if path: ResearchReviewWorkflowService(self.workspace, self.review_db).export_json(self.current_review_id, path)

    def _export_html(self):
        if not self.current_review_id: return
        path, _ = QFileDialog.getSaveFileName(self, 'Xuất HTML', 'research_review.html', 'HTML (*.html)')
        if path: ResearchReviewWorkflowService(self.workspace, self.review_db).export_html(self.current_review_id, path)

    def close(self, timeout_ms=5000):
        self.thread.quit(); self.thread.wait(timeout_ms)
