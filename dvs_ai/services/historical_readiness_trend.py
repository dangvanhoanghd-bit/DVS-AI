from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any

from .historical_candidate_store import CandidatePerformanceSnapshot, HistoricalCandidateStore


@dataclass(frozen=True)
class HistoricalReadinessResult:
    state: str
    candidate_id: str
    snapshots: int
    reasons: tuple[str, ...]
    metrics: dict[str, float]
    latest_snapshot_id: int | None


class HistoricalReadinessTrendAudit:
    """Observe-only readiness audit across persisted performance snapshots."""

    def __init__(self, *, min_snapshots: int = 4, recent_window: int = 4,
                 min_expectancy: float = 0.03, min_coverage: float = 0.50,
                 max_brier_degradation: float = 0.03,
                 max_drawdown_growth_ratio: float = 0.35,
                 min_positive_snapshot_ratio: float = 0.75,
                 min_non_degrading_ratio: float = 0.50) -> None:
        self.min_snapshots=max(2,int(min_snapshots)); self.recent_window=max(2,int(recent_window))
        self.min_expectancy=float(min_expectancy); self.min_coverage=float(min_coverage)
        self.max_brier_degradation=max(0.0,float(max_brier_degradation))
        self.max_drawdown_growth_ratio=max(0.0,float(max_drawdown_growth_ratio))
        self.min_positive_snapshot_ratio=min(1.0,max(0.0,float(min_positive_snapshot_ratio)))
        self.min_non_degrading_ratio=min(1.0,max(0.0,float(min_non_degrading_ratio)))

    @staticmethod
    def _finite(value: Any, default: float=0.0) -> float:
        try:
            number=float(value)
            return number if math.isfinite(number) else default
        except (TypeError,ValueError): return default

    def evaluate(self, candidate_id: str, snapshots: list[CandidatePerformanceSnapshot]) -> HistoricalReadinessResult:
        cid=str(candidate_id).strip(); rows=list(snapshots)
        latest_id=rows[-1].snapshot_id if rows else None
        if len(rows)<self.min_snapshots:
            return HistoricalReadinessResult("INSUFFICIENT_DATA",cid,len(rows),(f"snapshots {len(rows)} < {self.min_snapshots}",),{},latest_id)
        recent=rows[-min(self.recent_window,len(rows)):]
        expectancy=[self._finite(x.expectancy) for x in recent]
        drawdown=[max(0.0,self._finite(x.max_drawdown)) for x in recent]
        brier=[min(1.0,max(0.0,self._finite(x.brier))) for x in recent]
        coverage=[min(1.0,max(0.0,self._finite(x.coverage))) for x in recent]
        drift=[str(x.drift_state or "INSUFFICIENT_DATA").upper() for x in recent]
        positive_ratio=sum(v>=self.min_expectancy for v in expectancy)/len(expectancy)
        non_degrading=sum(expectancy[i]>=expectancy[i-1]-0.03 for i in range(1,len(expectancy)))/max(1,len(expectancy)-1)
        mean_exp=fmean(expectancy); std_exp=pstdev(expectancy) if len(expectancy)>1 else 0.0
        brier_delta=brier[-1]-brier[0]
        dd_base=max(drawdown[0],1e-9); dd_growth=(drawdown[-1]-drawdown[0])/dd_base if drawdown[0]>1e-9 else (0.0 if drawdown[-1]<=1e-9 else 1.0)
        metrics={"mean_expectancy":mean_exp,"expectancy_std":std_exp,"positive_snapshot_ratio":positive_ratio,
                 "non_degrading_ratio":non_degrading,"latest_expectancy":expectancy[-1],
                 "latest_drawdown":drawdown[-1],"drawdown_growth_ratio":dd_growth,
                 "brier_degradation":brier_delta,"minimum_coverage":min(coverage)}
        reasons=[]
        if any(x=="DRIFT" for x in drift):
            return HistoricalReadinessResult("CANDIDATE_UNSTABLE",cid,len(rows),("DRIFT present in recent snapshots",),metrics,latest_id)
        if expectancy[-1] < 0 or mean_exp < 0:
            return HistoricalReadinessResult("CANDIDATE_UNDERPERFORMS",cid,len(rows),("recent expectancy is negative",),metrics,latest_id)
        if any(x=="WATCH" for x in drift): reasons.append("WATCH present in recent snapshots")
        if min(coverage)<self.min_coverage: reasons.append("regime coverage below minimum")
        if brier_delta>self.max_brier_degradation: reasons.append("Brier degradation exceeds guardrail")
        if dd_growth>self.max_drawdown_growth_ratio: reasons.append("drawdown growth exceeds guardrail")
        if positive_ratio<self.min_positive_snapshot_ratio: reasons.append("positive snapshot ratio below minimum")
        if non_degrading<self.min_non_degrading_ratio: reasons.append("expectancy trend is unstable")
        if std_exp>max(0.08,abs(mean_exp)*1.5): reasons.append("expectancy dispersion is too high")
        if reasons:
            state="CANDIDATE_UNSTABLE" if any("unstable" in r or "drawdown" in r or "Brier" in r for r in reasons) else "CONTINUE_OBSERVATION"
            return HistoricalReadinessResult(state,cid,len(rows),tuple(reasons),metrics,latest_id)
        return HistoricalReadinessResult("READY_FOR_REVIEW",cid,len(rows),("stable across historical snapshot windows",),metrics,latest_id)


class HistoricalReadinessTrendStore:
    """Append-only readiness decisions keyed by candidate and snapshot."""
    def __init__(self, db_path: str="data/dvs_paper_trades.db") -> None:
        self.db_path=Path(db_path); self.db_path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS candidate_readiness_trend_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,candidate_id TEXT NOT NULL,snapshot_id INTEGER NOT NULL,
                evaluated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,state TEXT NOT NULL,reasons_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL,UNIQUE(candidate_id,snapshot_id))""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_readiness_trend_candidate ON candidate_readiness_trend_events(candidate_id,id)")

    def append_once(self,result: HistoricalReadinessResult) -> int | None:
        if result.latest_snapshot_id is None: return None
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cur=conn.execute("INSERT INTO candidate_readiness_trend_events(candidate_id,snapshot_id,state,reasons_json,metrics_json) VALUES (?,?,?,?,?)",
                    (result.candidate_id,result.latest_snapshot_id,result.state,json.dumps(result.reasons,ensure_ascii=False),json.dumps(result.metrics,sort_keys=True)))
                return int(cur.lastrowid)
        except sqlite3.IntegrityError: return None

    def events(self,candidate_id: str) -> list[dict[str,Any]]:
        with sqlite3.connect(str(self.db_path)) as conn:
            rows=conn.execute("SELECT id,snapshot_id,evaluated_at,state,reasons_json,metrics_json FROM candidate_readiness_trend_events WHERE candidate_id=? ORDER BY id",(candidate_id,)).fetchall()
        out=[]
        for row in rows:
            try: reasons=json.loads(row[4]); metrics=json.loads(row[5])
            except Exception: reasons=[]; metrics={}
            out.append({"id":row[0],"snapshot_id":row[1],"evaluated_at":row[2],"state":row[3],"reasons":reasons,"metrics":metrics})
        return out
