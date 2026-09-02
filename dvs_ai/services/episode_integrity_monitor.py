from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


class EpisodeIntegrityMonitor:
    """Read-only integrity diagnostics for episode/candidate/outcome infrastructure."""

    TABLES = {"setup_episodes", "episode_evaluations", "decision_candidates", "candidate_outcomes", "decision_diagnostic_traces"}

    def __init__(self, db_path: str | Path = "data/dvs_paper_trades.db") -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _parse(value: Any) -> datetime | None:
        if not value: return None
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError: return None

    def snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        if not self.db_path.exists():
            return self._result([], "UNOBSERVABLE", ["Database does not exist."], now)
        with self._connect() as con:
            existing = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = sorted(self.TABLES - existing)
            if missing:
                issues = [self._issue("MISSING_TABLE", "CRITICAL", t, "", f"Required table {t} is missing.") for t in missing]
                return self._result(issues, "FAILED", ["Canonical episode schema is incomplete."], now)
            issues: list[dict[str, Any]] = []

            def add(code: str, severity: str, entity: str, entity_id: Any, detail: str) -> None:
                issues.append(self._issue(code, severity, entity, entity_id, detail))

            for r in con.execute("""SELECT ev.evaluation_id,ev.setup_episode_id FROM episode_evaluations ev
                LEFT JOIN decision_diagnostic_traces dt ON dt.evaluation_id=ev.evaluation_id WHERE dt.evaluation_id IS NULL"""):
                add("MISSING_DIAGNOSTIC_TRACE", "WARNING", "evaluation", r["evaluation_id"], f"Episode {r['setup_episode_id']} has no diagnostic trace.")
            for r in con.execute("""SELECT dt.evaluation_id FROM decision_diagnostic_traces dt
                LEFT JOIN episode_evaluations ev ON ev.evaluation_id=dt.evaluation_id WHERE ev.evaluation_id IS NULL"""):
                add("ORPHAN_DIAGNOSTIC_TRACE", "ERROR", "trace", r["evaluation_id"], "Trace references no evaluation.")
            for r in con.execute("""SELECT ev.evaluation_id,ev.setup_episode_id FROM episode_evaluations ev
                LEFT JOIN setup_episodes e ON e.setup_episode_id=ev.setup_episode_id WHERE e.setup_episode_id IS NULL"""):
                add("ORPHAN_EVALUATION", "ERROR", "evaluation", r["evaluation_id"], f"Missing episode {r['setup_episode_id']}.")
            for r in con.execute("""SELECT c.candidate_id,c.setup_episode_id FROM decision_candidates c
                LEFT JOIN setup_episodes e ON e.setup_episode_id=c.setup_episode_id WHERE e.setup_episode_id IS NULL"""):
                add("ORPHAN_CANDIDATE", "CRITICAL", "candidate", r["candidate_id"], f"Missing episode {r['setup_episode_id']}.")
            for r in con.execute("""SELECT o.outcome_id,o.candidate_id FROM candidate_outcomes o
                LEFT JOIN decision_candidates c ON c.candidate_id=o.candidate_id WHERE c.candidate_id IS NULL"""):
                add("ORPHAN_OUTCOME", "CRITICAL", "outcome", r["outcome_id"], f"Missing candidate {r['candidate_id']}.")
            for r in con.execute("SELECT setup_episode_id,COUNT(*) n FROM decision_candidates GROUP BY setup_episode_id HAVING COUNT(*)>1"):
                add("DUPLICATE_ACTIVATION", "CRITICAL", "episode", r["setup_episode_id"], f"{r['n']} candidates reference one episode.")
            for r in con.execute("""SELECT e.setup_episode_id,e.activation_evaluation_id,c.activation_evaluation_id AS candidate_eval
                FROM setup_episodes e JOIN decision_candidates c ON c.setup_episode_id=e.setup_episode_id
                WHERE e.activation_evaluation_id IS NULL OR e.activation_evaluation_id<>c.activation_evaluation_id"""):
                add("ACTIVATION_LINK_MISMATCH", "ERROR", "episode", r["setup_episode_id"], f"episode={r['activation_evaluation_id']} candidate={r['candidate_eval']}")
            for r in con.execute("""SELECT e.setup_episode_id,e.decision_engine_profile_hash ed,c.decision_engine_profile_hash cd,
                e.trade_plan_profile_hash et,c.trade_plan_profile_hash ct FROM setup_episodes e JOIN decision_candidates c ON c.setup_episode_id=e.setup_episode_id
                WHERE e.decision_engine_profile_hash<>c.decision_engine_profile_hash OR e.trade_plan_profile_hash<>c.trade_plan_profile_hash"""):
                add("PROFILE_HASH_MISMATCH", "CRITICAL", "episode", r["setup_episode_id"], "Episode and candidate profile hashes differ.")
            for r in con.execute("""SELECT dt.evaluation_id,dt.setup_episode_id FROM decision_diagnostic_traces dt JOIN setup_episodes e ON e.setup_episode_id=dt.setup_episode_id
                WHERE dt.decision_engine_profile_hash<>e.decision_engine_profile_hash"""):
                add("TRACE_HASH_MISMATCH", "ERROR", "evaluation", r["evaluation_id"], f"Trace hash differs from episode {r['setup_episode_id']}.")
            for r in con.execute("SELECT setup_episode_id,evaluation_count FROM setup_episodes"):
                seqs=[x[0] for x in con.execute("SELECT sequence_number FROM episode_evaluations WHERE setup_episode_id=? ORDER BY sequence_number",(r['setup_episode_id'],))]
                expected=list(range(1,len(seqs)+1))
                if seqs!=expected: add("SEQUENCE_GAP", "ERROR", "episode", r["setup_episode_id"], f"sequence={seqs[:20]} expected contiguous 1..{len(seqs)}")
                if int(r["evaluation_count"] or 0)!=len(seqs): add("EVALUATION_COUNT_MISMATCH", "ERROR", "episode", r["setup_episode_id"], f"stored={r['evaluation_count']} actual={len(seqs)}")
            for r in con.execute("SELECT setup_episode_id,last_seen_at FROM setup_episodes WHERE status='OPEN'"):
                dt=self._parse(r["last_seen_at"])
                if dt and now-dt>timedelta(hours=2): add("STALE_OPEN_EPISODE", "WARNING", "episode", r["setup_episode_id"], f"No evaluation since {r['last_seen_at']} (>2h).")
            for r in con.execute("SELECT candidate_id,status,entry_expiry_at FROM decision_candidates"):
                expiry=self._parse(r["entry_expiry_at"])
                if r["status"]=="WAITING_ENTRY" and expiry and now>expiry: add("OVERDUE_WAITING_ENTRY", "ERROR", "candidate", r["candidate_id"], f"Expired at {r['entry_expiry_at']} but still WAITING_ENTRY.")
            for r in con.execute("SELECT outcome_id,candidate_id,status,resolution_claimed_at FROM candidate_outcomes WHERE status='RESOLVING'"):
                claimed=self._parse(r["resolution_claimed_at"])
                if claimed and now-claimed>timedelta(minutes=30): add("STALE_RESOLUTION_CLAIM", "ERROR", "outcome", r["outcome_id"], f"Candidate {r['candidate_id']} resolving since {r['resolution_claimed_at']} (>30m).")

        status = "HEALTHY" if not issues else ("FAILED" if any(i["severity"] in {"CRITICAL"} for i in issues) else "DEGRADED")
        notes=["Read-only diagnostic; no records were modified.", "Thresholds: open episode 2h; resolution claim 30m."]
        return self._result(issues,status,notes,now)

    @staticmethod
    def _issue(code: str, severity: str, entity: str, entity_id: Any, detail: str) -> dict[str, Any]:
        return {"code":code,"severity":severity,"entity":entity,"entity_id":str(entity_id or ""),"detail":detail}

    @staticmethod
    def _result(issues: list[dict[str, Any]], status: str, notes: list[str], now: datetime) -> dict[str, Any]:
        sev=Counter(i["severity"] for i in issues); codes=Counter(i["code"] for i in issues)
        return {"schema":"episode-integrity-v1","generated_at":now.isoformat(),"status":status,"issue_count":len(issues),
                "severity_counts":dict(sev),"code_counts":dict(codes),"issues":issues,"notes":notes}
