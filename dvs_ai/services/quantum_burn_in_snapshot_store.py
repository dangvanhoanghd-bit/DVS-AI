from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BurnInSnapshotStoreError(RuntimeError):
    pass


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class BurnInSnapshotStore:
    """Tamper-evident, append-only history of observe-only QBP-1 snapshots."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BurnInSnapshotStoreError(f"invalid snapshot JSON at line {number}") from exc
            if not isinstance(item, dict):
                raise BurnInSnapshotStoreError(f"invalid snapshot record at line {number}")
            rows.append(item)
        return rows

    def verify(self) -> bool:
        previous = "GENESIS"
        try:
            rows = self.read()
        except BurnInSnapshotStoreError:
            return False
        for index, row in enumerate(rows, 1):
            if row.get("sequence") != index or row.get("previous_hash") != previous:
                return False
            entry_hash = row.get("entry_hash")
            body = dict(row)
            body.pop("entry_hash", None)
            if entry_hash != _digest(body):
                return False
            if row.get("authority_granted") is not False:
                return False
            if row.get("production_or_execution_authority") is not False:
                return False
            previous = str(entry_hash)
        return True

    def append(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        if not self.verify():
            raise BurnInSnapshotStoreError("existing burn-in snapshot history is invalid")
        rows = self.read()
        body = {
            "schema": "DVS_QBP1_BURN_IN_SNAPSHOT_HISTORY_V1",
            "sequence": len(rows) + 1,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "snapshot_sha256": _digest(snapshot),
            "eligible_outcomes": int(snapshot.get("quality", {}).get("eligible", 0)),
            "stage": str(snapshot.get("burn_in", {}).get("stage", "UNKNOWN")),
            "dataset_sha256": str(snapshot.get("quality", {}).get("dataset_sha256", "")),
            "cross_pipeline_action": str(snapshot.get("cross_pipeline", {}).get("action", "UNKNOWN")),
            "previous_hash": rows[-1]["entry_hash"] if rows else "GENESIS",
            "authority_granted": False,
            "production_or_execution_authority": False,
        }
        body["entry_hash"] = _digest(body)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return body

    def write_latest_atomic(self, destination: str | Path, snapshot: dict[str, Any]) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
        fd, temp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return target
