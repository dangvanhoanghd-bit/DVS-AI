from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import itertools
import json
import os
from pathlib import Path
import threading
import time
import weakref
from typing import Any


def _forensic_mode_enabled() -> bool:
    return str(os.environ.get("DVS_FORENSIC_MODE", "0")).strip().lower() in {
        "1", "true", "yes", "on",
    }


@dataclass
class _TokenState:
    token: int
    object_id: int
    origin_cycle_index: int
    symbol: str
    created_monotonic: float
    ref: weakref.ReferenceType[Any]
    owners: set[str] = field(default_factory=set)
    last_cycle_seen: int = 0


class CoinAnalysisTokenTracker:
    """Weak-reference token tracker for CoinAnalysis reference-escape localization.

    The tracker never keeps a strong reference to a domain object. Object IDs are
    only lookup hints and are always validated with ``weakref() is obj`` before
    reuse, preventing CPython address reuse from aliasing an old token.
    """

    def __init__(self, output_path: str | Path = "artifacts/runtime/coin_analysis_token_events.jsonl"):
        self._output_path = Path(output_path)
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._sequence = itertools.count(1)
        self._token_sequence = itertools.count(1)
        self._by_object_id: dict[int, _TokenState] = {}
        self._by_token: dict[int, _TokenState] = {}
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self.enabled = _forensic_mode_enabled()

    def _write(self, event: str, state: _TokenState, *, cycle_index: int, owner_path: str | None = None, mutation_site: str | None = None, **extra: Any) -> None:
        if not self.enabled:
            return
        payload = {
            "schema_version": "dvs.runtime.coin_analysis_token.v1",
            "sequence": next(self._sequence),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "timestamp_monotonic": round(time.monotonic(), 6),
            "event": event,
            "token": state.token,
            "object_id_at_registration": hex(state.object_id),
            "symbol": state.symbol,
            "origin_cycle_index": state.origin_cycle_index,
            "current_cycle_index": int(cycle_index),
            "object_age_cycles": max(0, int(cycle_index) - state.origin_cycle_index),
            "owner_path": owner_path,
            "mutation_site": mutation_site,
            "active_owner_count": len(state.owners),
            "active_owners": sorted(state.owners),
            **extra,
        }
        try:
            # RC6.16 (causal fix): moved from a direct os.open/os.write/
            # os.close sequence (guarded by self._write_lock) to the
            # shared async JSONL writer. That direct sequence could run
            # on the GUI thread (this tracker is invoked from GUI-thread
            # owner-tracking call sites, not only workers) and perform
            # blocking disk I/O there; RC6.15's independent GUI hang
            # watchdog caught the GUI thread's Python stack inside this
            # exact call chain during several observed multi-second
            # stalls. A single dedicated background writer thread now
            # performs the actual write, and -- since only that one
            # thread ever touches the file -- self._write_lock is no
            # longer needed to prevent interleaving between callers.
            from dvs_ai.runtime.async_jsonl_writer import enqueue_jsonl_write
            enqueue_jsonl_write(self._output_path, payload)
        except Exception:
            pass

    def register_created(self, obj: Any, *, cycle_index: int, mutation_site: str, symbol: str | None = None) -> int | None:
        if not self.enabled:
            return None
        if obj is None:
            return None
        oid = id(obj)
        with self._lock:
            existing = self._by_object_id.get(oid)
            if existing is not None and existing.ref() is obj:
                return existing.token
            token = next(self._token_sequence)
            try:
                ref = weakref.ref(obj, lambda _ref, tok=token: self._on_collected(tok))
            except TypeError:
                return None
            state = _TokenState(
                token=token,
                object_id=oid,
                origin_cycle_index=int(cycle_index),
                symbol=str(symbol or getattr(obj, "symbol", "UNKNOWN")),
                created_monotonic=time.monotonic(),
                ref=ref,
                last_cycle_seen=int(cycle_index),
            )
            self._by_object_id[oid] = state
            self._by_token[token] = state
            self._write("token_created", state, cycle_index=cycle_index, mutation_site=mutation_site)
            return token

    def token_for(self, obj: Any, *, cycle_index: int, mutation_site: str, allow_adopt: bool = True) -> int | None:
        if not self.enabled:
            return None
        if obj is None:
            return None
        oid = id(obj)
        with self._lock:
            state = self._by_object_id.get(oid)
            if state is not None and state.ref() is obj:
                state.last_cycle_seen = max(state.last_cycle_seen, int(cycle_index))
                return state.token
        if allow_adopt:
            token = self.register_created(obj, cycle_index=cycle_index, mutation_site=f"late_adopt:{mutation_site}")
            if token is not None:
                state = self._by_token[token]
                self._write("token_late_adopted", state, cycle_index=cycle_index, mutation_site=mutation_site)
            return token
        return None

    def owner_enter(self, obj: Any, owner_path: str, *, cycle_index: int, mutation_site: str) -> int | None:
        if not self.enabled:
            return None
        token = self.token_for(obj, cycle_index=cycle_index, mutation_site=mutation_site)
        if token is None:
            return None
        with self._lock:
            state = self._by_token[token]
            state.owners.add(str(owner_path))
            state.last_cycle_seen = max(state.last_cycle_seen, int(cycle_index))
            self._write("token_entered_owner", state, cycle_index=cycle_index, owner_path=owner_path, mutation_site=mutation_site)
        return token

    def owner_release(self, obj: Any, owner_path: str, *, cycle_index: int, mutation_site: str) -> int | None:
        if not self.enabled:
            return None
        token = self.token_for(obj, cycle_index=cycle_index, mutation_site=mutation_site, allow_adopt=False)
        if token is None:
            return None
        with self._lock:
            state = self._by_token[token]
            existed = str(owner_path) in state.owners
            state.owners.discard(str(owner_path))
            self._write("token_released_from_owner", state, cycle_index=cycle_index, owner_path=owner_path, mutation_site=mutation_site, owner_was_registered=existed)
        return token

    def owner_transition(self, previous_obj: Any, new_obj: Any, owner_path: str, *, cycle_index: int, mutation_site: str) -> None:
        if not self.enabled:
            return
        """Record an exact single-reference owner replacement without retaining either object."""
        if previous_obj is new_obj:
            if new_obj is not None:
                self.owner_enter(new_obj, owner_path, cycle_index=cycle_index, mutation_site=f"{mutation_site}:same_object")
            return
        if previous_obj is not None:
            self.owner_release(previous_obj, owner_path, cycle_index=cycle_index, mutation_site=f"{mutation_site}:release")
        if new_obj is not None:
            self.owner_enter(new_obj, owner_path, cycle_index=cycle_index, mutation_site=f"{mutation_site}:enter")

    def qobject_owner_snapshot(self, obj: Any, owner_path: str, qobject: Any, *, cycle_index: int, mutation_site: str, receiver_count: int | None = None) -> None:
        if not self.enabled:
            return
        """Emit primitive-only Qt ownership evidence for a known CoinAnalysis owner."""
        token = self.token_for(obj, cycle_index=cycle_index, mutation_site=mutation_site, allow_adopt=False)
        if token is None:
            return
        with self._lock:
            state = self._by_token.get(token)
            if state is None:
                return
            parent = None
            children_count = None
            visible = None
            enabled = None
            try:
                parent_obj = qobject.parent()
                parent = type(parent_obj).__name__ if parent_obj is not None else None
            except Exception:
                pass
            try:
                children_count = len(qobject.children())
            except Exception:
                pass
            try:
                visible = bool(qobject.isVisible())
            except Exception:
                pass
            try:
                enabled = bool(qobject.isEnabled())
            except Exception:
                pass
            self._write(
                "qobject_owner_snapshot", state, cycle_index=cycle_index, owner_path=owner_path,
                mutation_site=mutation_site, qobject_class=type(qobject).__name__,
                qobject_parent_class=parent, qobject_children_count=children_count,
                qobject_visible=visible, qobject_enabled=enabled, receiver_count=receiver_count,
            )

    def cycle_snapshot(self, *, cycle_index: int) -> None:
        if not self.enabled:
            return
        with self._lock:
            for state in tuple(self._by_token.values()):
                if state.ref() is None:
                    continue
                state.last_cycle_seen = max(state.last_cycle_seen, int(cycle_index))
                self._write("token_seen_after_cycle", state, cycle_index=cycle_index, mutation_site="finalization_cycle_snapshot")

    def _on_collected(self, token: int) -> None:
        if not self.enabled:
            return
        with self._lock:
            state = self._by_token.pop(token, None)
            if state is None:
                return
            current = self._by_object_id.get(state.object_id)
            if current is state:
                self._by_object_id.pop(state.object_id, None)
            self._write("token_collected", state, cycle_index=state.last_cycle_seen, mutation_site="weakref_callback", lifetime_ms=round((time.monotonic() - state.created_monotonic) * 1000.0, 3))


COIN_ANALYSIS_TOKENS = CoinAnalysisTokenTracker()
