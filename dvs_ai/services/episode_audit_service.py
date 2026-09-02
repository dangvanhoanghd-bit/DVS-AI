from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class EpisodeAuditService:
    """Read-only episode/evaluation/candidate audit queries."""

    def __init__(self, db_path: str | Path = "data/dvs_paper_trades.db") -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _loads(value: Any, default: Any) -> Any:
        if value in (None, ""):
            return default
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default

    def list_episodes(self, *, limit: int = 500, symbol: str | None = None) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []
        where = "WHERE UPPER(e.symbol) LIKE ?" if symbol else ""
        params: tuple[Any, ...] = (f"%{symbol.strip().upper()}%",) if symbol else ()
        sql = f"""
            SELECT e.setup_episode_id,e.symbol,e.direction,e.status,e.started_at,e.last_seen_at,
                   e.evaluation_count,e.episode_class,e.activation_evaluation_id,e.candidate_id,
                   c.status AS candidate_status,o.status AS outcome_status,o.realized_r
            FROM setup_episodes e
            LEFT JOIN decision_candidates c ON c.candidate_id=e.candidate_id
            LEFT JOIN candidate_outcomes o ON o.candidate_id=c.candidate_id
            {where}
            ORDER BY e.last_seen_at DESC, e.setup_episode_id DESC
            LIMIT ?
        """
        with self._connect() as con:
            rows = con.execute(sql, (*params, max(1, min(int(limit), 5000)))).fetchall()
        return [dict(row) for row in rows]

    def episode_detail(self, episode_id: str) -> dict[str, Any]:
        if not self.db_path.exists():
            return {"episode": None, "evaluations": [], "candidate": None, "outcome": None, "timeline": []}
        with self._connect() as con:
            episode = con.execute("SELECT * FROM setup_episodes WHERE setup_episode_id=?", (episode_id,)).fetchone()
            if episode is None:
                return {"episode": None, "evaluations": [], "candidate": None, "outcome": None, "timeline": []}
            evaluations = con.execute("""
                SELECT ev.*,dt.trace_json,dt.created_at AS trace_created_at
                FROM episode_evaluations ev
                LEFT JOIN decision_diagnostic_traces dt ON dt.evaluation_id=ev.evaluation_id
                WHERE ev.setup_episode_id=? ORDER BY ev.sequence_number,ev.evaluated_at
            """, (episode_id,)).fetchall()
            candidate = con.execute("SELECT * FROM decision_candidates WHERE setup_episode_id=?", (episode_id,)).fetchone()
            outcome = None
            rejections: list[dict[str, Any]] = []
            if candidate is not None:
                outcome = con.execute("SELECT * FROM candidate_outcomes WHERE candidate_id=? ORDER BY updated_at DESC LIMIT 1", (candidate["candidate_id"],)).fetchone()
                rejections = [dict(r) for r in con.execute("SELECT gate_code,gate_ordinal FROM candidate_gate_rejections WHERE candidate_id=? ORDER BY gate_ordinal", (candidate["candidate_id"],)).fetchall()]

        ep = dict(episode)
        ep["initial_gate_set"] = self._loads(ep.get("initial_gate_set"), [])
        ep["activation_gate_set"] = self._loads(ep.get("activation_gate_set"), [])
        evaluation_items: list[dict[str, Any]] = []
        timeline: list[dict[str, Any]] = [{"time": ep["started_at"], "kind": "EPISODE_STARTED", "detail": ep["first_evaluation_id"]}]
        for row in evaluations:
            item = dict(row)
            item["gate_set"] = self._loads(item.pop("gate_set_json", None), [])
            item["trace"] = self._loads(item.pop("trace_json", None), {})
            evaluation_items.append(item)
            timeline.append({"time": item["evaluated_at"], "kind": "EVALUATION", "detail": f"#{item['sequence_number']} {item['evaluation_id']}"})
        candidate_item = dict(candidate) if candidate is not None else None
        outcome_item = dict(outcome) if outcome is not None else None
        if candidate_item:
            candidate_item["gate_rejections"] = rejections
            timeline.append({"time": candidate_item["activated_at"], "kind": "ACTIVATED", "detail": candidate_item["candidate_id"]})
            if candidate_item.get("fill_time"):
                timeline.append({"time": candidate_item["fill_time"], "kind": "ENTRY_FILLED", "detail": str(candidate_item.get("fill_price"))})
        if outcome_item and outcome_item.get("outcome_time"):
            timeline.append({"time": outcome_item["outcome_time"], "kind": outcome_item.get("status", "OUTCOME"), "detail": outcome_item.get("outcome_detail") or ""})
        if ep.get("closed_at"):
            timeline.append({"time": ep["closed_at"], "kind": "EPISODE_CLOSED", "detail": ep.get("status", "")})
        timeline.sort(key=lambda x: (x.get("time") or "", x.get("kind") or ""))
        return {"episode": ep, "evaluations": evaluation_items, "candidate": candidate_item, "outcome": outcome_item, "timeline": timeline}
