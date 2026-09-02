from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class IntegrityAlertPolicy:
    """Deterministic, read-only alert policy over the integrity incident ledger.

    The policy never changes the canonical episode database or incident state. It only
    records alert lifecycle metadata in the separate integrity ledger database.
    """

    SCHEMA_VERSION = "integrity-alert-policy-v1"
    POLICY_VERSION = "4.1.0-I-policy-1"
    LEVEL_RANK = {"NONE": 0, "NOTICE": 1, "WATCH": 2, "ALERT": 3, "URGENT": 4}

    def __init__(self, ledger_path: str | Path = "data/dvs_integrity_ledger.db") -> None:
        self.ledger_path = Path(ledger_path)

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def _connect(self) -> sqlite3.Connection:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.ledger_path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema(con)
        return con

    @staticmethod
    def _ensure_schema(con: sqlite3.Connection) -> None:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS integrity_alert_state (
                incident_key TEXT PRIMARY KEY,
                alert_level TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                first_alerted_at TEXT,
                last_evaluated_at TEXT NOT NULL,
                last_changed_at TEXT NOT NULL,
                reason_json TEXT NOT NULL,
                active INTEGER NOT NULL CHECK(active IN (0,1))
            );
            CREATE TABLE IF NOT EXISTS integrity_alert_events (
                event_id TEXT PRIMARY KEY,
                incident_key TEXT NOT NULL,
                event_time TEXT NOT NULL,
                event_type TEXT NOT NULL CHECK(event_type IN ('NEW','ESCALATED','DEESCALATED','ONGOING','CLEARED')),
                previous_level TEXT NOT NULL,
                current_level TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                reason_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_integrity_alert_events_time
                ON integrity_alert_events(event_time DESC);
            """
        )

    @classmethod
    def classify(cls, incident: dict[str, Any]) -> tuple[str, list[str]]:
        if str(incident.get("state", "")) != "OPEN":
            return "NONE", ["Incident is resolved."]

        severity = str(incident.get("severity", "INFO")).upper()
        age = max(0, int(incident.get("age_seconds", 0) or 0))
        occurrences = max(0, int(incident.get("occurrence_count", 0) or 0))
        recurrences = max(0, int(incident.get("recurrence_count", 0) or 0))
        reasons: list[str] = []

        if severity == "CRITICAL":
            return "URGENT", ["CRITICAL integrity incident requires immediate operator review."]

        if severity == "ERROR":
            level = "ALERT"
            reasons.append("ERROR integrity incident is active.")
            if age >= 3600 or recurrences >= 2:
                level = "URGENT"
                if age >= 3600:
                    reasons.append("ERROR has remained open for at least 60 minutes.")
                if recurrences >= 2:
                    reasons.append("ERROR has reopened at least twice.")
            elif age >= 900 or recurrences >= 1 or occurrences >= 4:
                reasons.append("ERROR persistence/recurrence threshold reached.")
            return level, reasons

        if severity == "WARNING":
            if age >= 21600 or recurrences >= 2:
                reasons.append("WARNING is long-lived or recurrent.")
                return "ALERT", reasons
            if age >= 7200 or recurrences >= 1 or occurrences >= 4:
                reasons.append("WARNING persistence threshold reached.")
                return "WATCH", reasons
            return "NOTICE", ["WARNING integrity incident is active."]

        # INFO and unknown severities are intentionally conservative.
        if age >= 86400 or recurrences >= 3:
            reasons.append("Informational incident persisted for 24 hours or recurred at least three times.")
            return "WATCH", reasons
        if occurrences >= 8:
            return "NOTICE", ["Informational incident observed at least eight times."]
        return "NONE", ["Below read-only alert policy thresholds."]

    def evaluate(self, ledger_snapshot: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        now = now or self._utc_now()
        evaluated_at = now.isoformat()
        incidents = list(ledger_snapshot.get("incidents") or [])
        current = {str(row.get("incident_key", "")): row for row in incidents if row.get("incident_key")}
        alerts: list[dict[str, Any]] = []
        transitions = {"new": [], "escalated": [], "deescalated": [], "ongoing": [], "cleared": []}

        with self._connect() as con:
            previous = {row["incident_key"]: dict(row) for row in con.execute("SELECT * FROM integrity_alert_state")}
            for key, incident in current.items():
                level, reasons = self.classify(incident)
                active = level != "NONE"
                old = previous.get(key)
                old_level = str(old["alert_level"]) if old else "NONE"
                old_rank = self.LEVEL_RANK.get(old_level, 0)
                new_rank = self.LEVEL_RANK.get(level, 0)
                if old is None and active:
                    event_type = "NEW"
                    transitions["new"].append(key)
                elif old_rank < new_rank:
                    event_type = "ESCALATED"
                    transitions["escalated"].append(key)
                elif old_rank > new_rank and active:
                    event_type = "DEESCALATED"
                    transitions["deescalated"].append(key)
                elif old and int(old.get("active", 0)) and not active:
                    event_type = "CLEARED"
                    transitions["cleared"].append(key)
                else:
                    event_type = "ONGOING"
                    if active:
                        transitions["ongoing"].append(key)

                changed = old is None or old_level != level or int(old.get("active", 0)) != int(active)
                first_alerted = old.get("first_alerted_at") if old else None
                if active and not first_alerted:
                    first_alerted = evaluated_at
                last_changed = evaluated_at if changed else str(old.get("last_changed_at", evaluated_at))
                con.execute(
                    """INSERT INTO integrity_alert_state
                       (incident_key,alert_level,policy_version,first_alerted_at,last_evaluated_at,last_changed_at,reason_json,active)
                       VALUES(?,?,?,?,?,?,?,?)
                       ON CONFLICT(incident_key) DO UPDATE SET
                         alert_level=excluded.alert_level,policy_version=excluded.policy_version,
                         first_alerted_at=excluded.first_alerted_at,last_evaluated_at=excluded.last_evaluated_at,
                         last_changed_at=excluded.last_changed_at,reason_json=excluded.reason_json,active=excluded.active""",
                    (key, level, self.POLICY_VERSION, first_alerted, evaluated_at, last_changed,
                     json.dumps(reasons, ensure_ascii=False), int(active)),
                )
                if changed:
                    con.execute(
                        """INSERT INTO integrity_alert_events
                           (event_id,incident_key,event_time,event_type,previous_level,current_level,policy_version,reason_json)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (str(uuid.uuid4()), key, evaluated_at, event_type, old_level, level,
                         self.POLICY_VERSION, json.dumps(reasons, ensure_ascii=False)),
                    )
                if active:
                    alerts.append({
                        **incident,
                        "alert_level": level,
                        "alert_reasons": reasons,
                        "alert_first_seen_at": first_alerted,
                        "alert_last_changed_at": last_changed,
                    })

            # Alert states whose incidents disappeared from the ledger are cleared.
            for key, old in previous.items():
                if key in current or not int(old.get("active", 0)):
                    continue
                reasons = ["Incident no longer exists in the active ledger view."]
                con.execute(
                    """UPDATE integrity_alert_state SET alert_level='NONE',active=0,last_evaluated_at=?,last_changed_at=?,reason_json=?
                       WHERE incident_key=?""",
                    (evaluated_at, evaluated_at, json.dumps(reasons), key),
                )
                con.execute(
                    """INSERT INTO integrity_alert_events
                       (event_id,incident_key,event_time,event_type,previous_level,current_level,policy_version,reason_json)
                       VALUES(?,?,?,?,?,'NONE',?,?)""",
                    (str(uuid.uuid4()), key, evaluated_at, "CLEARED", str(old.get("alert_level", "NONE")),
                     self.POLICY_VERSION, json.dumps(reasons)),
                )
                transitions["cleared"].append(key)
            con.commit()

            events = [dict(row) for row in con.execute(
                "SELECT * FROM integrity_alert_events ORDER BY event_time DESC LIMIT 100"
            )]

        alerts.sort(key=lambda row: (
            -self.LEVEL_RANK.get(str(row.get("alert_level", "NONE")), 0),
            -int(row.get("age_seconds", 0) or 0),
            str(row.get("code", "")),
        ))
        counts = {level: 0 for level in ("NOTICE", "WATCH", "ALERT", "URGENT")}
        for row in alerts:
            counts[row["alert_level"]] += 1
        overall = "URGENT" if counts["URGENT"] else "ALERT" if counts["ALERT"] else "WATCH" if counts["WATCH"] else "NOTICE" if counts["NOTICE"] else "CLEAR"
        return {
            "schema": self.SCHEMA_VERSION,
            "policy_version": self.POLICY_VERSION,
            "generated_at": evaluated_at,
            "status": overall,
            "active_alert_count": len(alerts),
            "level_counts": counts,
            "alerts": alerts,
            "events": events,
            "transitions": transitions,
            "policy": {
                "CRITICAL": "URGENT immediately",
                "ERROR": "ALERT immediately; URGENT after 60m or 2 recurrences",
                "WARNING": "NOTICE immediately; WATCH after 2h/1 recurrence/4 observations; ALERT after 6h/2 recurrences",
                "INFO": "WATCH after 24h or 3 recurrences; NOTICE after 8 observations",
            },
            "notes": [
                "Read-only alerting: no canonical data repair or state mutation.",
                "Alert metadata is stored only in the separate integrity ledger database.",
                "Decision Engine and trading thresholds are outside this policy boundary.",
            ],
        }
