"""
STUB tối giản cho PySide6.QtCore — CHỈ để kiểm tra main_window.py IMPORT
được thành công (bắt các lỗi như "import annotations" từng lọt qua vì
ast.parse() chỉ kiểm tra cú pháp, không kiểm tra import thật).

KHÔNG dùng để chạy GUI thật — hãy cài PySide6 thật cho việc đó.
"""
from __future__ import annotations


class _Signal:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return self

    def connect(self, *args, **kwargs):
        pass

    def emit(self, *args, **kwargs):
        pass

    def __get__(self, obj, objtype=None):
        return self


def Signal(*args, **kwargs):
    return _Signal()


def Slot(*args, **kwargs):
    def decorator(fn):
        return fn
    return decorator


class QObject:
    def __init__(self, *args, **kwargs):
        pass


class QThread(QObject):
    def start(self, *args, **kwargs):
        pass

    def quit(self):
        pass

    def isRunning(self):
        return False

    def wait(self, *args, **kwargs):
        return True


class QTimer(QObject):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.timeout = _Signal()

    def start(self, *args, **kwargs):
        pass

    def stop(self):
        pass

    def isActive(self):
        return False

    @staticmethod
    def singleShot(*args, **kwargs):
        callback = args[-1] if args and callable(args[-1]) else None
        if callback:
            callback()


class _QtNamespace:
    class AlignmentFlag:
        AlignCenter = AlignTop = AlignLeft = AlignRight = AlignVCenter = 0
    class ItemDataRole:
        UserRole = DisplayRole = 0
    class PenStyle:
        DashLine = SolidLine = 0
    class PenCapStyle:
        RoundCap = 0
    class SortOrder:
        DescendingOrder = AscendingOrder = 0
    class Orientation:
        Horizontal = Vertical = 0


Qt = _QtNamespace()


class QPointF:
    def __init__(self, *args, **kwargs):
        pass


class QRectF:
    def __init__(self, *args, **kwargs):
        pass

    def adjusted(self, *args, **kwargs):
        return self

    def left(self): return 0
    def right(self): return 0
    def top(self): return 0
    def bottom(self): return 0
    def width(self): return 0
    def height(self): return 0


class QSettings:
    def __init__(self, *args, **kwargs):
        self._data = {}

    def value(self, key, default=None, type=None):
        value = self._data.get(key, default)
        if type is not None and value is not None:
            try:
                return type(value)
            except Exception:
                return default
        return value

    def setValue(self, key, value):
        self._data[key] = value


class QDateTime:
    @staticmethod
    def currentDateTime():
        return QDateTime()

    def toString(self, *args, **kwargs):
        return "2026-07-16 00:00:00"
