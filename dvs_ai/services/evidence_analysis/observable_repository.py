from __future__ import annotations
import json, sqlite3
from pathlib import Path
from .observable_models import FrozenObservation, ObservableFilters

class ObservableRepository:
    """The only Evidence Analysis component allowed to access SQLite."""
    def __init__(self, db_path="data/dvs_paper_trades.db"): self.db_path=Path(db_path)
    @staticmethod
    def _selected(value): return str(value or "").upper() in {"READY","SETUP","RUNNING","TRADE"}
    @staticmethod
    def _quality(truth_json):
        try:
            p=json.loads(truth_json or "{}"); return str(p.get("order_flow_quality") or p.get("order_flow_gate") or "UNKNOWN").upper()
        except Exception: return "UNKNOWN"
    def fetch_intersection(self, filters: ObservableFilters)->tuple[FrozenObservation,...]:
        f=filters.normalized(); clauses=[]; params=[]
        for col,val in (("regime",f.regime),("direction",f.direction),("candidate_id",f.candidate_id)):
            if val is not None: clauses.append(f"UPPER({col})=?" if col!="candidate_id" else "candidate_id=?"); params.append(val)
        sql="SELECT id,created_at,candidate_id,symbol,direction,regime,baseline_decision,shadow_decision,outcome_r,truth_json FROM shadow_observations"
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        with sqlite3.connect(str(self.db_path)) as conn: rows=conn.execute(sql,params).fetchall()
        out=[]
        for r in rows:
            quality=self._quality(r[9])
            if f.order_flow_quality and quality != f.order_flow_quality: continue
            variants=(f.variant,) if f.variant else ("MAIN","SHADOW")
            for variant in variants:
                decision=r[6] if variant=="MAIN" else r[7]
                out.append(FrozenObservation(int(r[0]),str(r[1]),str(r[2]),str(r[3]),str(r[4]).upper(),str(r[5]).upper(),variant,quality,self._selected(decision),None if r[8] is None else float(r[8])))
        return tuple(out)
