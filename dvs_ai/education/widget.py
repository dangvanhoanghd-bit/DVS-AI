from __future__ import annotations
import html
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout,QLabel,QLineEdit,QListWidget,QListWidgetItem,QPushButton,QSplitter,QTextBrowser,QVBoxLayout,QWidget
from dvs_ai.education.library import StaticKnowledgeLibrary

class StaticKnowledgeLibraryWidget(QWidget):
    """Read-only Layer-A view; no runtime context, network, progress or bookmark path."""
    def __init__(self,parent=None):
        super().__init__(parent); self._library=StaticKnowledgeLibrary(); self._verification=self._library.verify(); self._visible=self._library.lessons
        root=QVBoxLayout(self); row=QHBoxLayout(); row.addWidget(QLabel("<b>Thư viện kiến thức Crypto</b>")); row.addStretch(1)
        self.search_box=QLineEdit(); self.search_box.setPlaceholderText("Tìm trong giáo trình tĩnh…"); self.search_box.textChanged.connect(self._search)
        clear=QPushButton("Xóa tìm kiếm"); clear.clicked.connect(self.search_box.clear); row.addWidget(self.search_box); row.addWidget(clear); root.addLayout(row)
        info=QLabel(f"Layer A · {self._verification['lesson_count']} bài · Read-only · Không dùng dữ liệu runtime"); info.setWordWrap(True); root.addWidget(info)
        split=QSplitter(Qt.Orientation.Horizontal,self); self.lesson_list=QListWidget(split); self.viewer=QTextBrowser(split); self.viewer.setOpenExternalLinks(False)
        self.lesson_list.currentItemChanged.connect(self._select); split.addWidget(self.lesson_list); split.addWidget(self.viewer); split.setStretchFactor(0,1); split.setStretchFactor(1,3); root.addWidget(split,1)
        self._populate(self._visible)
        if self._visible:self.lesson_list.setCurrentRow(0)

    def _populate(self,rows):
        self.lesson_list.clear()
        for x in rows:
            item=QListWidgetItem(f"{x.position:03d} · {x.title}"); item.setData(Qt.ItemDataRole.UserRole,x.lesson_id); self.lesson_list.addItem(item)

    def _search(self,text):
        self._visible=self._library.search(text); self._populate(self._visible)
        if self._visible:self.lesson_list.setCurrentRow(0)
        else:self.viewer.setPlainText("Không tìm thấy nội dung phù hợp.")

    def _select(self,current,previous):
        if current is None:return
        lesson_id=current.data(Qt.ItemDataRole.UserRole)
        if not lesson_id:return
        text=self._library.read_lesson(str(lesson_id)); safe="<html><body><pre style='white-space:pre-wrap;font-family:inherit'>"+html.escape(text)+"</pre></body></html>"; self.viewer.setHtml(safe)
