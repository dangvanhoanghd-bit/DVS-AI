from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class HoldoutManager:
    """One-use locked holdout registry backed by an append-only JSONL ledger."""

    def __init__(self, ledger_path: str | Path) -> None:
        self.path = Path(ledger_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def status(self, holdout_id: str) -> Dict[str, Any]:
        state = {"exists": False, "locked": False, "consumed": False}
        for event in self._events():
            if event.get("holdout_id") != holdout_id:
                continue
            state["exists"] = True
            if event["event"] == "LOCKED":
                state["locked"] = True
            elif event["event"] == "CONSUMED":
                state["consumed"] = True
        return state

    def lock(self, holdout_id: str, dataset_cutoff: str, policy_scope_id: str) -> None:
        state = self.status(holdout_id)
        if state["exists"]:
            raise ValueError("holdout already exists")
        self._append("LOCKED", holdout_id, dataset_cutoff, policy_scope_id)

    def consume(self, holdout_id: str, dataset_cutoff: str, policy_scope_id: str) -> None:
        state = self.status(holdout_id)
        if not state["locked"]:
            raise ValueError("holdout is not locked")
        if state["consumed"]:
            raise ValueError("holdout already consumed")
        self._append("CONSUMED", holdout_id, dataset_cutoff, policy_scope_id)

    def _append(self, event: str, holdout_id: str, dataset_cutoff: str, policy_scope_id: str) -> None:
        previous_hash = "GENESIS"
        events = self._events()
        if events:
            previous_hash = events[-1]["event_hash"]
        payload = {
            "event": event,
            "holdout_id": holdout_id,
            "dataset_cutoff": dataset_cutoff,
            "policy_scope_id": policy_scope_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "previous_hash": previous_hash,
        }
        payload["event_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, sort_keys=True) + "\n")
