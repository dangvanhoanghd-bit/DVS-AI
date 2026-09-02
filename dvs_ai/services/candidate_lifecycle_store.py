from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATES = (
    "CREATED", "BACKTESTED", "PENDING_REVIEW", "APPLIED_TO_SHADOW",
    "OBSERVING", "READY_FOR_REVIEW", "REJECTED", "ROLLED_BACK", "ARCHIVED",
)

_ALLOWED = {
    None: {"CREATED"},
    "CREATED": {"BACKTESTED", "REJECTED", "ARCHIVED"},
    "BACKTESTED": {"PENDING_REVIEW", "REJECTED", "ARCHIVED"},
    "PENDING_REVIEW": {"APPLIED_TO_SHADOW", "REJECTED", "ARCHIVED"},
    "APPLIED_TO_SHADOW": {"OBSERVING", "ROLLED_BACK", "ARCHIVED"},
    "OBSERVING": {"READY_FOR_REVIEW", "REJECTED", "ROLLED_BACK", "ARCHIVED"},
    "READY_FOR_REVIEW": {"OBSERVING", "REJECTED", "ROLLED_BACK", "ARCHIVED"},
    "REJECTED": {"ARCHIVED"},
    "ROLLED_BACK": {"ARCHIVED"},
    "ARCHIVED": set(),
}


@dataclass(frozen=True)
class LifecycleEvent:
    event_id: int
    candidate_id: str
    previous_state: str | None
    new_state: str
    occurred_at: str
    reason: str
    actor: str
    metadata: dict[str, Any]


class CandidateLifecycleStore:
    """Append-only, auditable candidate lifecycle. No promotion or execution APIs."""

    def __init__(self, db_path: str = "data/dvs_paper_trades.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS candidate_lifecycle_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id TEXT NOT NULL,
                    previous_state TEXT,
                    new_state TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candidate_lifecycle ON candidate_lifecycle_events(candidate_id,id)")

    def _connect(self):
        return sqlite3.connect(str(self.db_path))

    def current_state(self, candidate_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT new_state FROM candidate_lifecycle_events WHERE candidate_id=? ORDER BY id DESC LIMIT 1",
                (str(candidate_id),),
            ).fetchone()
        return str(row[0]) if row else None

    def transition(self, candidate_id: str, new_state: str, *, reason: str,
                   actor: str = "SYSTEM", metadata: dict | None = None,
                   occurred_at: str | None = None) -> int:
        cid = str(candidate_id).strip()
        state = str(new_state).strip().upper()
        if not cid:
            raise ValueError("candidate_id is required")
        if state not in STATES:
            raise ValueError(f"unsupported lifecycle state: {state}")
        previous = self.current_state(cid)
        if state not in _ALLOWED.get(previous, set()):
            raise ValueError(f"illegal lifecycle transition: {previous!r} -> {state}")
        stamp = occurred_at or datetime.now(timezone.utc).isoformat()
        payload = json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            cur = conn.execute("""
                INSERT INTO candidate_lifecycle_events
                (candidate_id,previous_state,new_state,occurred_at,reason,actor,metadata_json)
                VALUES (?,?,?,?,?,?,?)
            """, (cid, previous, state, stamp, str(reason), str(actor), payload))
            return int(cur.lastrowid)

    def events(self, candidate_id: str | None = None) -> list[LifecycleEvent]:
        sql = "SELECT id,candidate_id,previous_state,new_state,occurred_at,reason,actor,metadata_json FROM candidate_lifecycle_events"
        args: tuple[Any, ...] = ()
        if candidate_id is not None:
            sql += " WHERE candidate_id=?"
            args = (str(candidate_id),)
        sql += " ORDER BY id"
        with self._connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        result=[]
        for row in rows:
            try: metadata=json.loads(row[7]) if row[7] else {}
            except Exception: metadata={}
            result.append(LifecycleEvent(int(row[0]),str(row[1]),row[2],str(row[3]),str(row[4]),str(row[5]),str(row[6]),metadata))
        return result

    def candidates(self, *, include_archived: bool = True) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows=conn.execute("""
                SELECT e.candidate_id,e.new_state,e.occurred_at,e.reason,e.actor,
                       (SELECT MIN(occurred_at) FROM candidate_lifecycle_events x WHERE x.candidate_id=e.candidate_id) created_at
                FROM candidate_lifecycle_events e
                WHERE e.id=(SELECT MAX(id) FROM candidate_lifecycle_events z WHERE z.candidate_id=e.candidate_id)
                ORDER BY e.id DESC
            """).fetchall()
        out=[]
        for cid,state,updated,reason,actor,created in rows:
            if not include_archived and state == "ARCHIVED":
                continue
            out.append({"candidate_id":cid,"state":state,"created_at":created,"updated_at":updated,"reason":reason,"actor":actor})
        return out
