"""
STUB tối giản cho PySide6.QtWidgets — chỉ để kiểm tra IMPORT thành công.
Mọi phương thức đều no-op (không vẽ giao diện thật).
"""
from __future__ import annotations


class _NoopMeta(type):
    """Cho phép gọi bất kỳ method nào trên instance mà không lỗi (no-op)."""
    pass


class _BaseWidget:
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        def _noop(*args, **kwargs):
            return None
        return _noop


class QWidget(_BaseWidget):
    pass


class QMainWindow(_BaseWidget):
    pass


class QDialog(_BaseWidget):
    class DialogCode:
        Accepted = 1
        Rejected = 0

    def exec(self):
        return 0




class QLayout(_BaseWidget):
    class SizeConstraint:
        SetNoConstraint = 0


class QVBoxLayout(_BaseWidget):
    pass


class QHBoxLayout(_BaseWidget):
    pass


class QLabel(_BaseWidget):
    pass


class QPushButton(_BaseWidget):
    pass


class QProgressBar(_BaseWidget):
    pass


class QTableWidget(_BaseWidget):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self._row_count = 0

    def rowCount(self):
        return self._row_count

    def setRowCount(self, n):
        self._row_count = n

    def insertRow(self, *args, **kwargs):
        self._row_count += 1


class QTableWidgetItem(_BaseWidget):
    pass


class QHeaderView(_BaseWidget):
    class ResizeMode:
        ResizeToContents = 0
        Stretch = 1


class QTextEdit(_BaseWidget):
    pass


class QTabWidget(_BaseWidget):
    pass


class QSplitter(_BaseWidget):
    def __init__(self, *args, **kwargs):
        super().__init__()

    class Orientation:
        Horizontal = 0
        Vertical = 1


class QFrame(_BaseWidget):
    pass


class QLineEdit(_BaseWidget):
    pass


class QListWidget(_BaseWidget):
    pass


class QDialogButtonBox(_BaseWidget):
    class StandardButton:
        Save = 1
        Cancel = 2


class QMessageBox(_BaseWidget):
    @staticmethod
    def information(*args, **kwargs):
        pass

    @staticmethod
    def warning(*args, **kwargs):
        pass


class QAbstractItemView(_BaseWidget):
    class EditTrigger:
        NoEditTriggers = 0

    class SelectionBehavior:
        SelectRows = 0

    class SelectionMode:
        SingleSelection = 0


class QFileDialog(_BaseWidget):
    @staticmethod
    def getSaveFileName(*args, **kwargs):
        return ("", "")


class QApplication(_BaseWidget):
    def __init__(self, *args, **kwargs):
        super().__init__()

    @staticmethod
    def processEvents():
        pass


class QComboBox(_BaseWidget):
    pass


class QCompleter(_BaseWidget):
    class CompletionMode:
        PopupCompletion = 0
        InlineCompletion = 1
        UnfilteredPopupCompletion = 2

    class CaseSensitivity:
        CaseInsensitive = 0
        CaseSensitive = 1


class QGroupBox(_BaseWidget):
    pass


class QFormLayout(_BaseWidget):
    pass


class QScrollArea(_BaseWidget):
    pass


class QSizePolicy(_BaseWidget):
    pass
