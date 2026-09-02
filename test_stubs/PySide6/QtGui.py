from __future__ import annotations


class QColor:
    def __init__(self, *args, **kwargs):
        pass

    def setAlpha(self, *args):
        pass


class QPainter:
    class RenderHint:
        Antialiasing = 0

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        def _noop(*args, **kwargs):
            return None
        return _noop


class QPen:
    def __init__(self, *args, **kwargs):
        pass

    def setCapStyle(self, *args):
        pass


class QBrush:
    def __init__(self, *args, **kwargs):
        pass


class QFont:
    def __init__(self, *args, **kwargs):
        pass

    def setBold(self, *args):
        pass


class QKeySequence:
    def __init__(self, *args, **kwargs):
        pass


class QShortcut:
    def __init__(self, *args, **kwargs):
        self.activated = type("Signal", (), {"connect": lambda self, *a, **k: None})()
