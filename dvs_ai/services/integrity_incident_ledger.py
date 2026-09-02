from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dvs_ai.services.episode_integrity_monitor import EpisodeIntegrityMonitor


class IntegrityIncidentLedger:
    """Persist integrity snapshots and incident lifecycle in a separate audit ledger.

    The canonical episode database remains read-only. Only ``ledger_path`` is written.
    """

    SCHEMA_VERSION = "integrity-incident-ledger-v1"

    def __init__(
        self,
        source_db_path: str | Path = "data/dvs_paper_trades.db",
        ledger_path: str | Path = "data/dvs_integrity_ledger.db",
    ) -> None:
        self.source_db_path = Path(source_db_path)
        self.ledger_path = Path(ledger_path)
        self.monitor = EpisodeIntegrityMonitor(self.source_db_path)

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _fingerprint(issue: dict[str, Any]) -> str:
        identity = {
            "code": str(issue.get("code", "")),
            "entity": str(issue.get("entity", "")),
            "entity_id": str(issue.get("entity_id", "")),
        }
        payload = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.ledger_path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema(con)
        return con

    @staticmethod
    def _ensure_schema(con: sqlite3.Connection) -> None:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS integrity_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                generated_at TEXT NOT NULL,
                source_db_path TEXT NOT NULL,
                source_status TEXT NOT NULL,
                issue_count INTEGER NOT NULL,
                severity_counts_json TEXT NOT NULL,
                code_counts_json TEXT NOT NULL,
                notes_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS integrity_snapshot_issues (
                snapshot_id TEXT NOT NULL,
                incident_key TEXT NOT NULL,
                code TEXT NOT NULL,
                severity TEXT NOT NULL,
                entity TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                detail TEXT NOT NULL,
                PRIMARY KEY(snapshot_id, incident_key),
                FOREIGN KEY(snapshot_id) REFERENCES integrity_snapshots(snapshot_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS integrity_incidents (
                incident_key TEXT PRIMARY KEY,
                code TEXT NOT NULL,
                severity TEXT NOT NULL,
                entity TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                current_detail TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('OPEN','RESOLVED')),
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                resolved_at TEXT,
                occurrence_count INTEGER NOT NULL DEFAULT 1,
                recurrence_count INTEGER NOT NULL DEFAULT 0,
                first_snapshot_id TEXT NOT NULL,
                last_snapshot_id TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_integrity_incidents_state ON integrity_incidents(state, last_seen_at DESC);
            CREATE INDEX IF NOT EXISTS idx_integrity_snapshots_generated ON integrity_snapshots(generated_at DESC);
            """
        )

    def capture(self, *, now: datetime | None = None) -> dict[str, Any]:
        now = now or self._utc_now()
        source = self.monitor.snapshot(now=now)
        snapshot_id = str(uuid.uuid4())
        captured_at = str(source.get("generated_at") or now.isoformat())
        issues = list(source.get("issues") or [])
        current: dict[str, dict[str, Any]] = {self._fingerprint(issue): issue for issue in issues}
        transitions = {"new": [], "reopened": [], "ongoing": [], "resolved": []}

        with self._connect() as con:
            con.execute(
                """INSERT INTO integrity_snapshots
                   (snapshot_id,generated_at,source_db_path,source_status,issue_count,severity_counts_json,code_counts_json,notes_json)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    snapshot_id,
                    captured_at,
                    str(self.source_db_path),
                    str(source.get("status", "UNOBSERVABLE")),
                    int(source.get("issue_count", len(issues))),
                    json.dumps(source.get("severity_counts", {}), sort_keys=True),
                    json.dumps(source.get("code_counts", {}), sort_keys=True),
                    json.dumps(source.get("notes", []), ensure_ascii=False),
                ),
            )
            previous_open = {
                row["incident_key"]: dict(row)
                for row in con.execute("SELECT * FROM integrity_incidents WHERE state='OPEN'")
            }
            for key, issue in current.items():
                existing = con.execute("SELECT * FROM integrity_incidents WHERE incident_key=?", (key,)).fetchone()
                con.execute(
                    """INSERT INTO integrity_snapshot_issues
                       (snapshot_id,incident_key,code,severity,entity,entity_id,detail) VALUES(?,?,?,?,?,?,?)""",
                    (
                        snapshot_id,
                        key,
                        str(issue.get("code", "")),
                        str(issue.get("severity", "")),
                        str(issue.get("entity", "")),
                        str(issue.get("entity_id", "")),
                        str(issue.get("detail", "")),
                    ),
                )
                if existing is None:
                    con.execute(
                        """INSERT INTO integrity_incidents
                           (incident_key,code,severity,entity,entity_id,current_detail,state,first_seen_at,last_seen_at,resolved_at,occurrence_count,recurrence_count,first_snapshot_id,last_snapshot_id)
                           VALUES(?,?,?,?,?,?,'OPEN',?,?,NULL,1,0,?,?)""",
                        (
                            key,
                            str(issue.get("code", "")),
                            str(issue.get("severity", "")),
                            str(issue.get("entity", "")),
                            str(issue.get("entity_id", "")),
                            str(issue.get("detail", "")),
                            captured_at,
                            captured_at,
                            snapshot_id,
                            snapshot_id,
                        ),
                    )
                    transitions["new"].append(key)
                elif existing["state"] == "RESOLVED":
                    con.execute(
                        """UPDATE integrity_incidents SET severity=?,current_detail=?,state='OPEN',last_seen_at=?,resolved_at=NULL,
                           occurrence_count=occurrence_count+1,recurrence_count=recurrence_count+1,last_snapshot_id=? WHERE incident_key=?""",
                        (str(issue.get("severity", "")), str(issue.get("detail", "")), captured_at, snapshot_id, key),
                    )
                    transitions["reopened"].append(key)
                else:
                    con.execute(
                        """UPDATE integrity_incidents SET severity=?,current_detail=?,last_seen_at=?,occurrence_count=occurrence_count+1,last_snapshot_id=? WHERE incident_key=?""",
                        (str(issue.get("severity", "")), str(issue.get("detail", "")), captured_at, snapshot_id, key),
                    )
                    transitions["ongoing"].append(key)
            for key in sorted(set(previous_open) - set(current)):
                con.execute(
                    "UPDATE integrity_incidents SET state='RESOLVED',resolved_at=?,last_snapshot_id=? WHERE incident_key=?",
                    (captured_at, snapshot_id, key),
                )
                transitions["resolved"].append(key)
            con.commit()

        return self.snapshot(snapshot_id=snapshot_id, transitions=transitions)

    def snapshot(self, *, snapshot_id: str | None = None, transitions: dict[str, list[str]] | None = None) -> dict[str, Any]:
        if not self.ledger_path.exists():
            return {
                "schema": self.SCHEMA_VERSION,
                "status": "UNOBSERVABLE",
                "snapshot_count": 0,
                "open_incident_count": 0,
                "resolved_incident_count": 0,
                "incidents": [],
                "snapshots": [],
                "transitions": {"new": [], "reopened": [], "ongoing": [], "resolved": []},
            }
        with self._connect() as con:
            incident_rows = [dict(r) for r in con.execute(
                "SELECT * FROM integrity_incidents ORDER BY CASE state WHEN 'OPEN' THEN 0 ELSE 1 END, last_seen_at DESC, severity, code"
            )]
            snapshot_count = int(con.execute("SELECT COUNT(*) FROM integrity_snapshots").fetchone()[0])
            snapshots = [dict(r) for r in con.execute(
                "SELECT snapshot_id,generated_at,source_status,issue_count,severity_counts_json,code_counts_json FROM integrity_snapshots ORDER BY generated_at DESC LIMIT 100"
            )]
        now = self._utc_now()
        for row in incident_rows:
            first = datetime.fromisoformat(row["first_seen_at"].replace("Z", "+00:00"))
            end_raw = row["resolved_at"] if row["state"] == "RESOLVED" and row["resolved_at"] else now.isoformat()
            end = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
            row["age_seconds"] = max(0, int((end - first).total_seconds()))
        for row in snapshots:
            row["severity_counts"] = json.loads(row.pop("severity_counts_json"))
            row["code_counts"] = json.loads(row.pop("code_counts_json"))
        states = Counter(row["state"] for row in incident_rows)
        return {
            "schema": self.SCHEMA_VERSION,
            "status": "ACTIVE",
            "latest_snapshot_id": snapshot_id or (snapshots[0]["snapshot_id"] if snapshots else None),
            "snapshot_count": snapshot_count,
            "open_incident_count": states.get("OPEN", 0),
            "resolved_incident_count": states.get("RESOLVED", 0),
            "incidents": incident_rows,
            "snapshots": snapshots,
            "transitions": transitions or {"new": [], "reopened": [], "ongoing": [], "resolved": []},
            "notes": [
                "Canonical episode database remained read-only.",
                f"History is stored separately in {self.ledger_path}.",
                "Incident identity is code + entity + entity_id; detail changes do not create duplicates.",
            ],
        }
