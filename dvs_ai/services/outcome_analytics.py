from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
import sqlite3
import random
from collections import Counter, defaultdict

from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore

TERMINAL_DECISIVE = {"WIN", "LOSS"}
TERMINAL_ALL = {"WIN", "LOSS", "AMBIGUOUS", "EXPIRED_UNFILLED"}

@dataclass(frozen=True)
class GateMetric:
    gate_code: str
    rejected_decisive: int
    accepted_decisive: int
    true_rejection: int
    false_rejection: int
    true_acceptance: int
    false_acceptance: int
    rejection_precision: float | None
    rejection_recall: float | None
    false_rejection_rate: float | None
    net_gate_value_r: float | None

@dataclass(frozen=True)
class CalibrationBin:
    lower: int
    upper: int
    samples: int
    wins: int
    losses: int
    actual_win_rate: float | None
    average_realized_r: float | None
    average_confidence: float | None

@dataclass(frozen=True)
class CohortMetric:
    key: str
    samples: int
    wins: int
    losses: int
    win_rate: float | None
    average_realized_r: float | None

class OutcomeAnalyticsService:
    """Read-only episode-level analytics. It never changes decision authority."""
    def __init__(self, store: OutcomeInfrastructureStore) -> None:
        self.store = store

    def _rows(self) -> list[dict[str, Any]]:
        # Hardening: analytics is enforced read-only by SQLite, not merely by code discipline.
        db_path = Path(self.store.db_path).resolve()
        if not db_path.is_file():
            raise FileNotFoundError(db_path)
        uri = f"file:{db_path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=30) as con:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA query_only=ON")
            rows = con.execute("""
                SELECT e.setup_episode_id,e.symbol,e.direction,e.episode_class,e.lifecycle_family,
                       e.evaluation_count,e.activation_evaluation_id,c.candidate_id,c.cohort,
                       o.status AS outcome_status,o.realized_r,o.outcome_time,
                       c.activated_at,
                       ev.entry_score,ev.confidence,ev.opportunity_score,ev.gate_set_json
                FROM setup_episodes e
                JOIN decision_candidates c ON c.setup_episode_id=e.setup_episode_id
                JOIN candidate_outcomes o ON o.candidate_id=c.candidate_id
                LEFT JOIN episode_evaluations ev
                  ON ev.setup_episode_id=e.setup_episode_id
                 AND ev.evaluation_id=e.activation_evaluation_id
            """).fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            try: item['gates']=tuple(json.loads(item.pop('gate_set_json') or '[]'))
            except Exception: item['gates']=()
            result.append(item)
        return result

    @staticmethod
    def _rate(n: int, d: int) -> float | None:
        return n / d if d else None

    def gate_effectiveness(self) -> list[GateMetric]:
        rows=[r for r in self._rows() if r['outcome_status'] in TERMINAL_DECISIVE]
        gates=sorted({g for r in rows for g in r['gates']})
        metrics=[]
        for gate in gates:
            rejected=[r for r in rows if gate in r['gates']]
            accepted=[r for r in rows if gate not in r['gates']]
            tr=sum(r['outcome_status']=='LOSS' for r in rejected)
            fr=sum(r['outcome_status']=='WIN' for r in rejected)
            ta=sum(r['outcome_status']=='WIN' for r in accepted)
            fa=sum(r['outcome_status']=='LOSS' for r in accepted)
            rejected_r=sum(float(r['realized_r'] or 0.0) for r in rejected)
            accepted_r=sum(float(r['realized_r'] or 0.0) for r in accepted)
            # Positive means the gate avoided more losing R than winning R it rejected.
            net=(-rejected_r / len(rejected)) if rejected else None
            metrics.append(GateMetric(gate,len(rejected),len(accepted),tr,fr,ta,fa,
                self._rate(tr,tr+fr),self._rate(tr,tr+fa),self._rate(fr,tr+fr),net))
        return metrics

    def calibration(self, width: int = 10) -> list[CalibrationBin]:
        rows=[r for r in self._rows() if r['outcome_status'] in TERMINAL_DECISIVE and r['confidence'] is not None]
        bins=[]
        for lower in range(0,100,width):
            upper=100 if lower+width>=100 else lower+width
            items=[r for r in rows if lower <= float(r['confidence']) <= upper if upper==100] if upper==100 else [r for r in rows if lower <= float(r['confidence']) < upper]
            wins=sum(r['outcome_status']=='WIN' for r in items); losses=len(items)-wins
            bins.append(CalibrationBin(lower,upper,len(items),wins,losses,self._rate(wins,len(items)),
                (sum(float(r['realized_r'] or 0) for r in items)/len(items)) if items else None,
                (sum(float(r['confidence']) for r in items)/len(items)) if items else None))
        return bins

    def cohorts(self, field: str) -> list[CohortMetric]:
        allowed={'cohort','symbol','direction','lifecycle_family'}
        if field not in allowed: raise ValueError(f'Unsupported cohort field: {field}')
        rows=[r for r in self._rows() if r['outcome_status'] in TERMINAL_DECISIVE]
        keys=sorted({str(r.get(field) or 'UNKNOWN') for r in rows})
        out=[]
        for key in keys:
            items=[r for r in rows if str(r.get(field) or 'UNKNOWN')==key]
            wins=sum(r['outcome_status']=='WIN' for r in items); losses=len(items)-wins
            out.append(CohortMetric(key,len(items),wins,losses,self._rate(wins,len(items)),
                sum(float(r['realized_r'] or 0) for r in items)/len(items)))
        return out


    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not value:
            return None
        text=str(value).strip().replace('Z','+00:00')
        for candidate in (text, text.replace(' UTC','+00:00')):
            try:
                dt=datetime.fromisoformat(candidate)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return None

    def reliability(self, cluster_minutes: int = 15, bootstrap_iterations: int = 2000, seed: int = 410) -> dict[str, Any]:
        rows=[r for r in self._rows() if r['outcome_status'] in TERMINAL_DECISIVE]
        n=len(rows)
        clusters: dict[str,list[dict[str,Any]]]=defaultdict(list)
        for row in rows:
            dt=self._parse_time(row.get('outcome_time')) or self._parse_time(row.get('activated_at'))
            if dt is None:
                key='UNKNOWN_TIME'
            else:
                minute=(dt.minute//cluster_minutes)*cluster_minutes
                key=dt.replace(minute=minute,second=0,microsecond=0).isoformat()
            clusters[key].append(row)
        cluster_sizes=[len(v) for v in clusters.values()]
        symbol_sizes=list(Counter(str(r.get('symbol') or 'UNKNOWN') for r in rows).values())
        def kish(sizes: list[int]) -> float:
            total=sum(sizes)
            return (total*total/sum(x*x for x in sizes)) if sizes and sum(x*x for x in sizes) else 0.0
        temporal_ess=kish(cluster_sizes)
        symbol_ess=kish(symbol_sizes)
        conservative=min(float(n),temporal_ess or float(n),symbol_ess or float(n)) if n else 0.0
        cluster_count=len(clusters)
        if n==0:
            status='UNOBSERVABLE'; reason='No decisive WIN/LOSS outcomes.'
        elif n<30 or cluster_count<10 or conservative<10:
            status='INSUFFICIENT'; reason='Fewer than 30 decisive episodes, 10 market-event clusters, or ESS below 10.'
        elif n<100 or conservative<30:
            status='EXPLORATORY'; reason='Descriptive evidence only; replication is required.'
        else:
            status='RELIABLE_DESCRIPTIVE'; reason='Adequate for descriptive monitoring, not automatic tuning.'
        ci={'win_rate_95':None,'average_realized_r_95':None}
        if clusters and cluster_count>=2 and bootstrap_iterations>0:
            rng=random.Random(seed); groups=list(clusters.values()); wr=[]; ar=[]
            for _ in range(bootstrap_iterations):
                sample=[]
                for _ in groups: sample.extend(rng.choice(groups))
                if sample:
                    wr.append(sum(x['outcome_status']=='WIN' for x in sample)/len(sample))
                    ar.append(sum(float(x['realized_r'] or 0) for x in sample)/len(sample))
            def bounds(values):
                values=sorted(values); m=len(values)
                return [values[max(0,int(.025*m))], values[min(m-1,int(.975*m))]] if m else None
            ci={'win_rate_95':bounds(wr),'average_realized_r_95':bounds(ar)}
        size_counts=Counter(cluster_sizes)
        cluster_size_distribution=[
            {'cluster_size':size,'cluster_count':count,'episode_count':size*count}
            for size,count in sorted(size_counts.items())
        ]
        return {
            'decisive_episode_count':n,'market_event_cluster_minutes':cluster_minutes,
            'market_event_cluster_count':cluster_count,'largest_cluster_size':max(cluster_sizes,default=0),
            'cluster_size_distribution':cluster_size_distribution,
            'unique_symbol_count':len(symbol_sizes),'temporal_cluster_ess':round(temporal_ess,3),
            'symbol_concentration_ess':round(symbol_ess,3),'conservative_effective_sample_size':round(conservative,3),
            'reliability_status':status,'status_reason':reason,'clustered_bootstrap':ci,
            'bootstrap_iterations':bootstrap_iterations,'bootstrap_seed':seed,
        }

    def snapshot(self) -> dict[str, Any]:
        rows=self._rows(); statuses={s:sum(r['outcome_status']==s for r in rows) for s in sorted(TERMINAL_ALL|{'PENDING','RESOLVING'})}
        return {
            'schema_version':'outcome-analytics-v2',
            'generated_at':datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
            'statistical_unit':'SETUP_EPISODE',
            'evaluation_count':sum(int(r['evaluation_count'] or 0) for r in rows),
            'episode_count':len(rows),
            'unique_symbols':len({r['symbol'] for r in rows}),
            'outcome_funnel':statuses,
            'statistical_reliability':self.reliability(),
            'gate_effectiveness':[asdict(x) for x in self.gate_effectiveness()],
            'calibration':[asdict(x) for x in self.calibration()],
            'cohorts':{f:[asdict(x) for x in self.cohorts(f)] for f in ('cohort','direction','lifecycle_family','symbol')},
            'known_limitations':{
                'cross_symbol_dependence':'Different symbols are treated as separate observations. Shared BTC shocks, broad market moves, and sector correlation are not yet controlled; effective independent sample size may be lower than observed episode count.',
                'small_sample_policy':'Metrics are descriptive. No promotion or threshold change is authorized by this report.',
                'cluster_definition':'Market-event clusters use 15-minute UTC windows based on outcome_time, falling back to candidate activation time. This is a dependence guard, not proof of independence.'
            },
            'safety_boundary':{'decision_engine_frozen':True,'automatic_tuning':False,'exchange_order_capability':False},
        }

    def export_json(self, destination: str|Path) -> Path:
        p=Path(destination); p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(self.snapshot(),ensure_ascii=False,indent=2),encoding='utf-8'); return p

    def render_html(self) -> str:
        s=self.snapshot()
        gate_rows=''.join(f"<tr><td>{escape(x['gate_code'])}</td><td>{x['rejected_decisive']}</td><td>{x['true_rejection']}</td><td>{x['false_rejection']}</td><td>{'' if x['rejection_precision'] is None else f'{x['rejection_precision']*100:.1f}%'} </td></tr>" for x in s['gate_effectiveness']) or '<tr><td colspan="5">No decisive outcomes</td></tr>'
        cal_rows=''.join(f"<tr><td>{x['lower']}-{x['upper']}</td><td>{x['samples']}</td><td>{'' if x['actual_win_rate'] is None else f'{x['actual_win_rate']*100:.1f}%'} </td><td>{'' if x['average_realized_r'] is None else f'{x['average_realized_r']:.3f}'}</td></tr>" for x in s['calibration'])
        return f'''<!doctype html><html><head><meta charset="utf-8"><title>DVS AI Outcome Analytics</title><style>body{{font-family:Arial;margin:32px;color:#17202a}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccd6e0;padding:7px}}th{{background:#eef4f8}}.warn{{background:#fff7e6;border-left:4px solid #aa6d00;padding:12px}}</style></head><body><h1>Outcome Analytics — Episode Level</h1><p>Generated {escape(s['generated_at'])}</p><p>Episodes: {s['episode_count']} · Evaluations: {s['evaluation_count']} · Symbols: {s['unique_symbols']}</p><h2>Gate Effectiveness</h2><table><tr><th>Gate</th><th>Rejected N</th><th>True rejection</th><th>False rejection</th><th>Precision</th></tr>{gate_rows}</table><h2>Calibration</h2><table><tr><th>Confidence</th><th>N</th><th>Actual win rate</th><th>Average R</th></tr>{cal_rows}</table><h2>Statistical Reliability</h2><p>Status: <b>{escape(s['statistical_reliability']['reliability_status'])}</b> · Observed decisive N: {s['statistical_reliability']['decisive_episode_count']} · Conservative ESS: {s['statistical_reliability']['conservative_effective_sample_size']} · Event clusters: {s['statistical_reliability']['market_event_cluster_count']}</p><div class="warn">{escape(s['statistical_reliability']['status_reason'])}</div><h2>Known Statistical Limitations</h2><div class="warn"><b>Cross-Symbol Dependence:</b> {escape(s['known_limitations']['cross_symbol_dependence'])}</div><h2>Safety Boundary</h2><p>Decision Engine frozen. Automatic tuning disabled. No exchange order capability.</p></body></html>'''

    def export_html(self,destination:str|Path)->Path:
        p=Path(destination); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(self.render_html(),encoding='utf-8'); return p
