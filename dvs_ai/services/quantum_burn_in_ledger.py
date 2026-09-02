from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BurnInLedgerError(RuntimeError):
    pass


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class BurnInMilestoneLedger:
    """Append-only, hash-chained ledger for observed burn-in milestones."""

    THRESHOLDS = (30, 100, 300, 500)

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise BurnInLedgerError(f"invalid ledger JSON at line {number}") from exc
        return rows

    def verify(self) -> bool:
        previous = "GENESIS"
        try:
            rows = self.read()
        except BurnInLedgerError:
            return False
        for index, row in enumerate(rows, 1):
            if row.get("sequence") != index or row.get("previous_hash") != previous:
                return False
            entry_hash = row.get("entry_hash")
            body = dict(row)
            body.pop("entry_hash", None)
            if entry_hash != _hash(body):
                return False
            previous = str(entry_hash)
        return True

    def record_reached(self, *, eligible_outcomes: int, dataset_sha256: str) -> list[dict[str, Any]]:
        if not self.verify():
            raise BurnInLedgerError("existing burn-in ledger is invalid")
        rows = self.read()
        reached = {int(row["threshold"]) for row in rows}
        previous = rows[-1]["entry_hash"] if rows else "GENESIS"
        appended: list[dict[str, Any]] = []
        for threshold in self.THRESHOLDS:
            if eligible_outcomes < threshold or threshold in reached:
                continue
            body = {
                "schema": "DVS_QBP_BURN_IN_MILESTONE_V1",
                "sequence": len(rows) + len(appended) + 1,
                "threshold": threshold,
                "eligible_outcomes_observed": int(eligible_outcomes),
                "dataset_sha256": str(dataset_sha256),
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "previous_hash": previous,
                "authority_granted": False,
                "paper_authority_handover_granted": False,
                "production_or_execution_authority": False,
            }
            body["entry_hash"] = _hash(body)
            previous = body["entry_hash"]
            appended.append(body)
        if appended:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                for row in appended:
                    handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        return appended
