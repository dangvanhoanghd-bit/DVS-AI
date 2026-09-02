from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AttemptLedger:
    """QG-16 append-only cross-run attempt accounting."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def append(self, policy_scope_hash: str, study_id: str, candidate_count: int, holdout_count: int) -> dict[str, Any]:
        if candidate_count < 0 or holdout_count < 0:
            raise ValueError("counts must be non-negative")
        entries = self.entries()
        previous_hash = entries[-1]["entry_hash"] if entries else "GENESIS"
        prior_attempts = sum(1 for e in entries if e["policy_scope_hash"] == policy_scope_hash)
        payload = {
            "policy_scope_hash": policy_scope_hash,
            "study_id": study_id,
            "attempt_count": prior_attempts + 1,
            "candidate_count": candidate_count,
            "holdout_count": holdout_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "previous_hash": previous_hash,
        }
        payload["entry_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, sort_keys=True) + "\n")
        return payload

    def verify(self) -> bool:
        previous = "GENESIS"
        attempts: dict[str, int] = {}
        for entry in self.entries():
            recorded = entry.get("entry_hash")
            body = dict(entry)
            body.pop("entry_hash", None)
            expected = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if recorded != expected or body.get("previous_hash") != previous:
                return False
            scope = str(body["policy_scope_hash"])
            attempts[scope] = attempts.get(scope, 0) + 1
            if body.get("attempt_count") != attempts[scope]:
                return False
            previous = recorded
        return True
