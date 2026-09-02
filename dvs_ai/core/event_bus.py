from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from threading import RLock

from .events import DomainEvent

EventHandler = Callable[[DomainEvent], None]


class EventBus:
    """Synchronous, deterministic in-process event bus.

    Handler failures are isolated and returned to the caller so the application
    layer can remain fail-closed without silently losing diagnostics.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._lock = RLock()

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        if not event_name.strip():
            raise ValueError("event_name is required")
        with self._lock:
            if handler not in self._handlers[event_name]:
                self._handlers[event_name].append(handler)

    def publish(self, event: DomainEvent) -> tuple[Exception, ...]:
        with self._lock:
            handlers = tuple(self._handlers.get(event.name, ())) + tuple(self._handlers.get("*", ()))
        failures: list[Exception] = []
        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:  # containment boundary
                failures.append(exc)
        return tuple(failures)
