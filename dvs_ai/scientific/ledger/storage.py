from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from threading import RLock
from typing import Protocol

from .models import ScientificLedgerEvent


class LedgerStorage(Protocol):
    def append(self, event: ScientificLedgerEvent) -> None: ...
    def read_run(self, pipeline_run_id: str) -> tuple[ScientificLedgerEvent, ...]: ...


class InMemoryLedgerStorage:
    def __init__(self) -> None:
        self._events: list[ScientificLedgerEvent] = []
        self._lock = RLock()

    def append(self, event: ScientificLedgerEvent) -> None:
        with self._lock:
            self._events.append(event)

    def read_run(self, pipeline_run_id: str) -> tuple[ScientificLedgerEvent, ...]:
        with self._lock:
            return tuple(event for event in self._events if event.pipeline_run_id == pipeline_run_id)

    def discard_run(self, pipeline_run_id: str) -> int:
        """Drop transient in-memory events for a completed observe-only run."""
        with self._lock:
            before = len(self._events)
            self._events = [e for e in self._events if e.pipeline_run_id != pipeline_run_id]
            return before - len(self._events)

    def event_count(self) -> int:
        """Return a lightweight count without exposing retained event objects."""
        with self._lock:
            return len(self._events)


class JsonLinesLedgerStorage:
    """Durable append-only JSONL storage. Existing bytes are never rewritten."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def append(self, event: ScientificLedgerEvent) -> None:
        line = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()

    def read_run(self, pipeline_run_id: str) -> tuple[ScientificLedgerEvent, ...]:
        if not self.path.exists():
            return ()
        events: list[ScientificLedgerEvent] = []
        with self._lock, self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("pipeline_run_id") != pipeline_run_id:
                    continue
                from ..contracts import ScientificLifecycleState
                events.append(ScientificLedgerEvent(
                    event_id=item["event_id"], pipeline_run_id=item["pipeline_run_id"],
                    sequence=int(item["sequence"]), timestamp_utc=item["timestamp_utc"], stage=item["stage"],
                    state_before=ScientificLifecycleState(item["state_before"]),
                    state_after=ScientificLifecycleState(item["state_after"]), succeeded=bool(item["succeeded"]),
                    reason_codes=tuple(item.get("reason_codes", ())), artifact_reference=item.get("artifact_reference"),
                    previous_hash=item["previous_hash"], event_hash=item["event_hash"],
                ))
        return tuple(events)
