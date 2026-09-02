from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from typing import Protocol, Sequence

from .mapping import OutcomeMappingError, map_episode_outcome, map_legacy_outcome
from .models import UnifiedOutcome


class OutcomeSource(Protocol):
    def read_terminal(self) -> Sequence[UnifiedOutcome]: ...


def _readonly_connection(path: Path) -> sqlite3.Connection:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    con = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


class PaperTradeSource:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def read_terminal(self) -> list[UnifiedOutcome]:
        if not self.db_path.is_file():
            return []
        with _readonly_connection(self.db_path) as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "paper_trades" not in tables:
                return []
            columns = {r[1] for r in con.execute("PRAGMA table_info(paper_trades)")}
            def expr(name: str, fallback: str = "NULL") -> str:
                return name if name in columns else fallback
            rows = con.execute(f"""
                SELECT id,created_at,{expr('closed_at')} AS closed_at,
                       {expr('symbol', "''")} AS symbol,{expr('direction', "''")} AS direction,
                       status,result,{expr('r_multiple')} AS r_multiple,
                       {expr('confidence')} AS confidence,{expr('entry_score')} AS entry_score,
                       {expr('risk_score')} AS risk_score,{expr('rr_planned')} AS rr_planned,
                       {expr('lab')} AS lab,{expr('pilot_id')} AS pilot_id,{expr('regime')} AS regime,
                       {expr('evidence_snapshot_json', "''")} AS evidence_snapshot_json,
                       {expr('setup_tags', "''")} AS setup_tags,
                       {expr('decision_id', "''")} AS decision_id,
                       {expr('candidate_id', "''")} AS candidate_id,
                       {expr('outcome_id', "''")} AS outcome_id
                FROM paper_trades
                WHERE status='CLOSED'
                ORDER BY created_at ASC,id ASC
            """).fetchall()
        out: list[UnifiedOutcome] = []
        for row in rows:
            try:
                mapped = map_legacy_outcome(
                    status=row["status"], result=row["result"], realized_r=row["r_multiple"]
                )
            except OutcomeMappingError:
                continue
            snapshot = None
            raw_snapshot = str(row["evidence_snapshot_json"] or "")
            if raw_snapshot:
                try:
                    value = json.loads(raw_snapshot)
                    snapshot = value if isinstance(value, dict) else None
                except (TypeError, ValueError, json.JSONDecodeError):
                    snapshot = None
            out.append(UnifiedOutcome(
                source="paper_trades",
                source_id=str(row["id"]),
                symbol=str(row["symbol"]),
                direction=str(row["direction"]),
                setup_time=str(row["created_at"]),
                close_time=str(row["closed_at"]) if row["closed_at"] else None,
                outcome=mapped.unified,
                realized_r=float(row["r_multiple"]) if row["r_multiple"] is not None else None,
                confidence=float(row["confidence"]) if row["confidence"] is not None else None,
                entry_score=float(row["entry_score"]) if row["entry_score"] is not None else None,
                risk_score=float(row["risk_score"]) if row["risk_score"] is not None else None,
                rr_planned=float(row["rr_planned"]) if row["rr_planned"] is not None else None,
                cohort=str(row["lab"]) if row["lab"] is not None else None,
                regime=str(row["regime"]) if row["regime"] is not None else None,
                evidence_snapshot=snapshot,
                original_status=mapped.original_status,
                original_result=mapped.original_result,
                provenance={
                    "mapping_rule_id": mapped.rule_id,
                    "legacy_pilot_id": row["pilot_id"],
                    "storage_table": "paper_trades",
                    "evidence_snapshot_present": bool(raw_snapshot),
                    "setup_tags": str(row["setup_tags"] or ""),
                    "decision_id": row["decision_id"],
                    "candidate_id": row["candidate_id"],
                    "outcome_id": row["outcome_id"],
                },
            ))
        return out


class EpisodeOutcomeSource:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def read_terminal(self) -> list[UnifiedOutcome]:
        if not self.db_path.is_file():
            return []
        with _readonly_connection(self.db_path) as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required = {"setup_episodes", "decision_candidates", "candidate_outcomes"}
            if not required.issubset(tables):
                return []
            rows = con.execute("""
                SELECT e.setup_episode_id,e.started_at,e.closed_at,e.symbol,e.direction,
                       c.candidate_id,c.cohort,c.rr_planned,c.activated_at,
                       o.outcome_id,o.status,o.realized_r,o.outcome_time,
                       ev.confidence,ev.entry_score
                FROM setup_episodes e
                JOIN decision_candidates c ON c.setup_episode_id=e.setup_episode_id
                JOIN candidate_outcomes o ON o.candidate_id=c.candidate_id
                LEFT JOIN episode_evaluations ev
                  ON ev.setup_episode_id=e.setup_episode_id
                 AND ev.evaluation_id=e.activation_evaluation_id
                WHERE o.status IN ('WIN','LOSS','AMBIGUOUS','EXPIRED_UNFILLED')
                ORDER BY COALESCE(o.outcome_time,c.activated_at,e.started_at),o.outcome_id
            """).fetchall()
        out: list[UnifiedOutcome] = []
        for row in rows:
            mapped = map_episode_outcome(status=row["status"])
            out.append(UnifiedOutcome(
                source="candidate_outcomes",
                source_id=str(row["outcome_id"]),
                symbol=str(row["symbol"]),
                direction=str(row["direction"]),
                setup_time=str(row["activated_at"] or row["started_at"]),
                close_time=str(row["outcome_time"] or row["closed_at"]) if (row["outcome_time"] or row["closed_at"]) else None,
                outcome=mapped.unified,
                realized_r=float(row["realized_r"]) if row["realized_r"] is not None else None,
                confidence=float(row["confidence"]) if row["confidence"] is not None else None,
                entry_score=float(row["entry_score"]) if row["entry_score"] is not None else None,
                risk_score=None,
                rr_planned=float(row["rr_planned"]) if row["rr_planned"] is not None else None,
                cohort=str(row["cohort"]) if row["cohort"] is not None else None,
                regime=None,
                evidence_snapshot=None,
                original_status=mapped.original_status,
                original_result=mapped.original_result,
                provenance={
                    "mapping_rule_id": mapped.rule_id,
                    "setup_episode_id": row["setup_episode_id"],
                    "candidate_id": row["candidate_id"],
                    "storage_table": "candidate_outcomes",
                },
            ))
        return out
