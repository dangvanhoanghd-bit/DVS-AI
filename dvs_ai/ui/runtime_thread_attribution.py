from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True)
class ThreadObservation:
    name: str
    ident: int | None
    native_id: int | None
    daemon: bool
    alive: bool
    first_seen_cycle: int
    last_seen_cycle: int
    age_cycles: int
    category: str


class RuntimeThreadAttributionTracker:
    """Bounded, read-only Python thread inventory for runtime qualification.

    The tracker does not create, stop, rename, or otherwise alter threads.  It
    records only live ``threading.Thread`` objects exposed by
    ``threading.enumerate()`` and keeps bounded metadata keyed by thread ident.
    """

    def __init__(self, *, max_retired: int = 128) -> None:
        self._first_seen: dict[tuple[int | None, str], int] = {}
        self._last_seen: dict[tuple[int | None, str], int] = {}
        self._previous_live: set[tuple[int | None, str]] = set()
        self._retired: list[dict] = []
        self._max_retired = max(16, int(max_retired))
        self._started_monotonic = time.monotonic()

    @staticmethod
    def _category(name: str) -> str:
        lowered = name.lower()
        if name == "MainThread":
            return "main"
        if lowered.startswith("dvs-scan"):
            return "scan_executor"
        if "order-flow" in lowered or "websocket" in lowered or "ws" in lowered:
            return "network_stream"
        if lowered.startswith("threadpoolexecutor"):
            return "unnamed_executor"
        if lowered.startswith("timer"):
            return "timer"
        if "dummy" in lowered:
            return "dummy"
        return "other"

    @staticmethod
    def _key(thread: threading.Thread) -> tuple[int | None, str]:
        return (thread.ident, thread.name)

    def snapshot(self, cycle: int) -> dict:
        cycle = max(0, int(cycle))
        live_threads: Iterable[threading.Thread] = tuple(threading.enumerate())
        live_keys: set[tuple[int | None, str]] = set()
        observations: list[ThreadObservation] = []

        for thread in live_threads:
            key = self._key(thread)
            live_keys.add(key)
            first = self._first_seen.setdefault(key, cycle)
            self._last_seen[key] = cycle
            observations.append(
                ThreadObservation(
                    name=thread.name,
                    ident=thread.ident,
                    native_id=getattr(thread, "native_id", None),
                    daemon=bool(thread.daemon),
                    alive=bool(thread.is_alive()),
                    first_seen_cycle=first,
                    last_seen_cycle=cycle,
                    age_cycles=max(0, cycle - first),
                    category=self._category(thread.name),
                )
            )

        new_keys = live_keys - self._previous_live
        retired_keys = self._previous_live - live_keys
        for key in sorted(retired_keys, key=lambda value: (str(value[1]), str(value[0]))):
            self._retired.append({
                "ident": key[0],
                "name": key[1],
                "first_seen_cycle": self._first_seen.get(key, cycle),
                "last_seen_cycle": self._last_seen.get(key, cycle),
            })
        if len(self._retired) > self._max_retired:
            self._retired = self._retired[-self._max_retired:]

        self._previous_live = live_keys
        inventory = [asdict(item) for item in sorted(
            observations,
            key=lambda item: (item.category, item.name, item.ident or -1),
        )]
        new_threads = [item for item in inventory if (item["ident"], item["name"]) in new_keys]
        persistent_threads = [item for item in inventory if item["age_cycles"] >= 2]
        category_counts: dict[str, int] = {}
        for item in inventory:
            category_counts[item["category"]] = category_counts.get(item["category"], 0) + 1

        return {
            "cycle": cycle,
            "uptime_seconds": round(time.monotonic() - self._started_monotonic, 3),
            "thread_count": len(inventory),
            "category_counts": category_counts,
            "new_threads": new_threads,
            "persistent_threads": persistent_threads,
            "retired_threads": list(self._retired),
            "inventory": inventory,
        }
