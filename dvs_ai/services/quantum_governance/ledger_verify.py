from __future__ import annotations

import hashlib
import json
from pathlib import Path


def verify_holdout_ledger(path: str | Path) -> bool:
    ledger = Path(path)
    if not ledger.is_file():
        return False
    previous = "GENESIS"
    state: dict[str, str] = {}
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
        for line in lines:
            if not line.strip():
                continue
            event = json.loads(line)
            recorded = event.get("event_hash")
            body = dict(event)
            body.pop("event_hash", None)
            expected = hashlib.sha256(
                json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if recorded != expected or body.get("previous_hash") != previous:
                return False
            holdout_id = str(body.get("holdout_id", ""))
            action = body.get("event")
            prior = state.get(holdout_id)
            if action == "LOCKED":
                if prior is not None:
                    return False
                state[holdout_id] = "LOCKED"
            elif action == "CONSUMED":
                if prior != "LOCKED":
                    return False
                state[holdout_id] = "CONSUMED"
            else:
                return False
            previous = recorded
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return True
