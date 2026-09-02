from __future__ import annotations
from collections.abc import Callable
from .models import Alert

AlertSink = Callable[[Alert], None]

class AlertCenter:
    def __init__(self, *, max_history: int = 1000) -> None:
        if max_history <= 0:
            raise ValueError("max_history must be positive")
        self.max_history = max_history
        self._history: list[Alert] = []
        self._sinks: list[AlertSink] = []

    def add_sink(self, sink: AlertSink) -> None:
        self._sinks.append(sink)

    def publish(self, alert: Alert) -> None:
        self._history.append(alert)
        del self._history[:-self.max_history]
        for sink in tuple(self._sinks):
            try:
                sink(alert)
            except Exception:
                continue

    def history(self, *, code: str | None = None) -> tuple[Alert, ...]:
        items = self._history if code is None else [a for a in self._history if a.code == code]
        return tuple(items)
