from __future__ import annotations

import json
import math
import gc
import time
from collections import OrderedDict
import random
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .quantum_data_convergence import QuantumDataAdapter
from .unified_outcome_service import UnifiedOutcomeService
from .legacy_path_telemetry import emit_legacy_sql_path_used


@dataclass
class OptimizationParams:
    main_confidence: float = 68.0
    main_entry: float = 62.0
    main_risk_max: float = 50.0
    main_rr_min: float = 1.8
    shadow_confidence: float = 45.0
    shadow_entry: float = 45.0
    shadow_risk_max: float = 65.0
    shadow_rr_min: float = 1.4
    weight_timing: float = 0.22
    weight_entry: float = 0.18
    weight_order_flow: float = 0.32
    weight_direction: float = 0.16
    weight_market: float = 0.12

    def clamp(self) -> "OptimizationParams":
        self.main_confidence = min(78.0, max(60.0, self.main_confidence))
        self.main_entry = min(75.0, max(55.0, self.main_entry))
        self.main_risk_max = min(60.0, max(35.0, self.main_risk_max))
        self.main_rr_min = min(2.5, max(1.4, self.main_rr_min))
        self.shadow_confidence = min(60.0, max(38.0, self.shadow_confidence))
        self.shadow_entry = min(60.0, max(38.0, self.shadow_entry))
        self.shadow_risk_max = min(75.0, max(45.0, self.shadow_risk_max))
        self.shadow_rr_min = min(2.0, max(1.1, self.shadow_rr_min))
        weights = [
            max(0.05, min(0.45, float(self.weight_timing))),
            max(0.05, min(0.45, float(self.weight_entry))),
            max(0.10, min(0.40, float(self.weight_order_flow))),
            max(0.05, min(0.35, float(self.weight_direction))),
            max(0.05, min(0.30, float(self.weight_market))),
        ]
        total = sum(weights) or 1.0
        (self.weight_timing, self.weight_entry, self.weight_order_flow,
         self.weight_direction, self.weight_market) = [v / total for v in weights]
        return self


@dataclass(frozen=True)
class ClosedTrade:
    created_at: str
    lab: str
    confidence: float
    entry_score: float
    risk_score: float
    rr_planned: float
    r_multiple: float
    setup_tags: str
    evidence_scores: tuple[float, float, float, float, float] = (50.0, 50.0, 50.0, 50.0, 50.0)


class QuantumOptimizer:
    """
    Quantum-inspired genetic optimizer.

    This is not quantum computing. It uses a genetic search over historical
    closed Paper Trades with chronological train/validation evaluation.
    Production parameters are never changed silently.
    """

    def __init__(
        self,
        db_path: str = "data/dvs_paper_trades.db",
        config_path: str = "config.json",
        population_size: int = 64,
        generations: int = 40,
        mutation_rate: float = 0.24,
        validation_ratio: float = 0.30,
        min_closed: int = 80,
        seed: int = 42,
        min_validation_selected: int = 20,
        min_validation_improvement: float = 2.0,
        max_validation_dd_increase: float = 1.0,
        fitness_cache_size: int = 500,
        gc_every_generations: int = 1,
        outcome_adapter: QuantumDataAdapter | None = None,
        unified_service: UnifiedOutcomeService | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.config_path = Path(config_path)
        self.outcome_adapter = outcome_adapter
        self.unified_service = unified_service or UnifiedOutcomeService(self.db_path)
        self.population_size = max(20, int(population_size))
        self.generations = max(10, int(generations))
        self.mutation_rate = max(0.05, min(0.80, mutation_rate))
        self.validation_ratio = max(0.20, min(0.40, validation_ratio))
        self.min_closed = max(40, int(min_closed))
        self.min_validation_selected = max(
            12, int(min_validation_selected)
        )
        self.min_validation_improvement = max(
            0.5, float(min_validation_improvement)
        )
        self.max_validation_dd_increase = max(
            0.0, float(max_validation_dd_increase)
        )
        self.random = random.Random(seed)
        self.fitness_cache_size = max(50, int(fitness_cache_size))
        self.gc_every_generations = max(1, int(gc_every_generations))
        self._fitness_cache = OrderedDict()
        self._last_training_audit = {
            "total_closed": 0,
            "eligible": 0,
            "excluded_missing_snapshot": 0,
            "excluded_invalid_snapshot": 0,
            "excluded_calibration": 0,
            "excluded_drift": 0,
            "excluded_order_flow_quality": 0,
        }


    @staticmethod
    def _chronological_split(
        rows: list[ClosedTrade],
        validation_ratio: float,
    ) -> tuple[list[ClosedTrade], list[ClosedTrade]]:
        """
        Walk-forward split. Never shuffle: all training trades must be older
        than all validation trades.
        """
        if not rows:
            return [], []
        split = max(
            1,
            min(
                len(rows)-1,
                int(len(rows) * (1.0-validation_ratio)),
            ),
        )
        return rows[:split], rows[split:]

    def _search_penalty(self) -> float:
        """
        Conservative penalty for trying many parameter combinations.

        This does not eliminate multiple-comparison risk, but requires a larger
        validation improvement when population/generation search is broader.
        """
        trials = max(1, self.population_size * self.generations)
        return 0.22 * math.log1p(trials)

    @staticmethod
    def _valid_evidence_snapshot(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        required = ("TIMING", "ENTRY", "ORDER_FLOW", "DIRECTION", "MARKET")
        for family in required:
            item = payload.get(family)
            if not isinstance(item, dict):
                return False
            if not bool(item.get("available", False)):
                return False
            try:
                score = float(item.get("score"))
                quality = float(item.get("quality"))
            except (TypeError, ValueError):
                return False
            if not math.isfinite(score) or not math.isfinite(quality):
                return False
            if not (0.0 <= quality <= 1.0):
                return False
        truth = payload.get("_TRUTH")
        return isinstance(truth, dict) and truth.get("schema") == "DVS_QUANTUM_TRAINING_V1"

    def _load_closed(self) -> list[ClosedTrade]:
        """Load governed Unified eligible records.

        Passing ``outcome_adapter`` is retained only as a deprecated audit
        compatibility path. Runtime defaults never use that path.
        """
        audit = {
            "total_closed": 0, "eligible": 0,
            "excluded_missing_snapshot": 0, "excluded_invalid_snapshot": 0,
            "excluded_calibration": 0, "excluded_drift": 0,
            "excluded_order_flow_quality": 0, "excluded_non_determinate": 0,
            "excluded_missing_optimizer_fields": 0,
            "source_paper_trades": 0, "source_candidate_outcomes": 0,
            "source_unified": 0,
        }
        self._last_training_audit = audit
        if self.outcome_adapter is not None:
            emit_legacy_sql_path_used(__name__, "QuantumOptimizer._load_closed", "INJECTED_RAW_ADAPTER")
            try:
                raw_rows = self.outcome_adapter.read_terminal()
            except (FileNotFoundError, sqlite3.Error, ValueError):
                return []
            rows = [r for r in raw_rows if r.outcome in ("WIN", "LOSS")]
            audit["excluded_non_determinate"] = len(raw_rows) - len(rows)
            # Compatibility only: preserve old tests/injected audits, never runtime default.
            normalized = rows
        else:
            try:
                normalized = self.unified_service.learning_ready()
                if not normalized and not self.unified_service.pipeline_schema_available():
                    normalized = self.unified_service.legacy_compat_learning_ready()
            except (FileNotFoundError, sqlite3.Error, ValueError):
                return []
        audit["total_closed"] = len(normalized)
        eligible: list[ClosedTrade] = []
        for row in normalized:
            if hasattr(row, "outcome_status"):
                snapshot = row.evidence_snapshot
                confidence, entry_score = row.confidence, row.entry_score
                risk_score, rr_planned, realized_r = row.risk_score, row.rr_planned, row.realized_r
                setup_time, cohort, setup_tags = row.setup_time, row.cohort, row.setup_tags
                audit["source_unified"] += 1
            else:
                snapshot = row.evidence_snapshot
                confidence, entry_score = row.confidence, row.entry_score
                risk_score, rr_planned, realized_r = row.risk_score, row.rr_planned, row.realized_r
                setup_time, cohort = row.setup_time, row.cohort
                setup_tags = str(row.provenance.get("setup_tags", ""))
                key = f"source_{row.source}"
                if key in audit: audit[key] += 1
            if snapshot is None:
                audit["excluded_missing_snapshot"] += 1; continue
            if not self._valid_evidence_snapshot(snapshot):
                audit["excluded_invalid_snapshot"] += 1; continue
            truth = snapshot["_TRUTH"]
            if str(truth.get("calibration_state", "")).upper() != "VALIDATED":
                audit["excluded_calibration"] += 1; continue
            if str(truth.get("drift_state", "")).upper() != "STABLE":
                audit["excluded_drift"] += 1; continue
            if str(truth.get("order_flow_quality", "")).upper() != "FULL":
                audit["excluded_order_flow_quality"] += 1; continue
            required = (confidence, entry_score, risk_score, rr_planned, realized_r)
            if any(value is None for value in required):
                audit["excluded_missing_optimizer_fields"] += 1; continue
            eligible.append(ClosedTrade(
                created_at=str(setup_time), lab=str(cohort or "SHADOW").upper(),
                confidence=float(confidence), entry_score=float(entry_score),
                risk_score=float(risk_score), rr_planned=float(rr_planned),
                r_multiple=float(realized_r), setup_tags=str(setup_tags),
                evidence_scores=tuple(float(snapshot[name].get("score", 50.0)) for name in ("TIMING","ENTRY","ORDER_FLOW","DIRECTION","MARKET")),
            ))
        audit["eligible"] = len(eligible)
        return eligible

    @staticmethod
    def _shadow_fusion_score(t: ClosedTrade, p: OptimizationParams) -> float:
        weights = (p.weight_timing, p.weight_entry, p.weight_order_flow,
                   p.weight_direction, p.weight_market)
        return sum(score * weight for score, weight in zip(t.evidence_scores, weights))

    @staticmethod
    def _passes(t: ClosedTrade, p: OptimizationParams, lab: str) -> bool:
        if lab == 'MAIN':
            return (
                t.confidence >= p.main_confidence
                and t.entry_score >= p.main_entry
                and t.risk_score <= p.main_risk_max
                and t.rr_planned >= p.main_rr_min
            )
        return (
            t.confidence >= p.shadow_confidence
            and QuantumOptimizer._shadow_fusion_score(t, p) >= p.shadow_entry
            and t.risk_score <= p.shadow_risk_max
            and t.rr_planned >= p.shadow_rr_min
            and 'MATURITY_LATE' not in t.setup_tags
            and 'MATURITY_EXHAUSTION' not in t.setup_tags
            and 'TREND_LATE_TREND' not in t.setup_tags
            and 'TREND_EXHAUSTION' not in t.setup_tags
            and 'MICRO_CONFLICT' not in t.setup_tags
            and 'MICRO_STRONG_CONFLICT' not in t.setup_tags
            and 'MICRO_COS_LOW' not in t.setup_tags
        )

    @staticmethod
    def _stats(rows: Iterable[ClosedTrade]) -> dict:
        rs=[x.r_multiple for x in rows]
        n=len(rs)
        if not n:
            return {'n':0,'wr':0.0,'avg_r':0.0,'pf':0.0,'max_dd':0.0}
        wins=sum(1 for r in rs if r>0)
        gross_win=sum(r for r in rs if r>0)
        gross_loss=abs(sum(r for r in rs if r<0))
        pf=(gross_win/gross_loss) if gross_loss>0 else (4.0 if gross_win>0 else 0.0)
        equity=peak=0.0
        max_dd=0.0
        for r in rs:
            equity += r
            peak=max(peak,equity)
            max_dd=max(max_dd,peak-equity)
        return {
            'n':n,'wr':wins/n*100.0,'avg_r':sum(rs)/n,
            'pf':min(4.0,pf),'max_dd':max_dd,
        }


    @staticmethod
    def _params_key(p: OptimizationParams) -> tuple:
        return tuple(round(float(getattr(p, name)), 6)
                     for name in OptimizationParams.__dataclass_fields__)

    def _cache_get(self, key: tuple):
        value = self._fitness_cache.get(key)
        if value is not None:
            self._fitness_cache.move_to_end(key)
        return value

    def _cache_put(self, key: tuple, value) -> None:
        self._fitness_cache[key] = value
        self._fitness_cache.move_to_end(key)
        while len(self._fitness_cache) > self.fitness_cache_size:
            self._fitness_cache.popitem(last=False)

    def clear_runtime_cache(self) -> None:
        self._fitness_cache.clear()
        gc.collect()

    def _score(self, rows: list[ClosedTrade], p: OptimizationParams) -> tuple[float,dict]:
        cache_key=(id(rows),len(rows),self._params_key(p))
        cached=self._cache_get(cache_key)
        if cached is not None:
            return cached
        selected=[]
        for t in rows:
            lab='MAIN' if t.lab=='MAIN' else 'SHADOW'
            if self._passes(t,p,lab): selected.append(t)
        s=self._stats(selected)
        minimum=max(12,int(len(rows)*0.12))
        if s['n'] < minimum:
            result=(-999.0,s)
            self._cache_put(cache_key,result)
            return result
        coverage=s['n']/max(1,len(rows))
        score=(
            42.0*s['avg_r']
            + 0.18*s['wr']
            + 7.5*s['pf']
            + 8.0*min(0.6,coverage)
            - 2.8*s['max_dd']
        )
        result=(score,s)
        self._cache_put(cache_key,result)
        return result

    def _base_params(self) -> OptimizationParams:
        raw=json.loads(self.config_path.read_text(encoding='utf-8'))
        defaults = OptimizationParams()
        values = {
            k: float(raw.get(k, getattr(defaults, k)))
            for k in (
                'main_confidence','main_entry','main_risk_max','main_rr_min',
                'shadow_confidence','shadow_entry','shadow_risk_max','shadow_rr_min',
            )
        }
        configured = dict(raw.get('evidence_fusion_family_weights', {}) or {})
        values.update({
            'weight_timing': float(configured.get('TIMING', defaults.weight_timing)),
            'weight_entry': float(configured.get('ENTRY', defaults.weight_entry)),
            'weight_order_flow': float(configured.get('ORDER_FLOW', defaults.weight_order_flow)),
            'weight_direction': float(configured.get('DIRECTION', defaults.weight_direction)),
            'weight_market': float(configured.get('MARKET', defaults.weight_market)),
        })
        return OptimizationParams(**values).clamp()

    def _random_params(self, base: OptimizationParams) -> OptimizationParams:
        p=OptimizationParams(**asdict(base))
        spans={
            'shadow_confidence':8,'shadow_entry':8,'shadow_risk_max':8,'shadow_rr_min':0.3,
            'weight_timing':0.08,'weight_entry':0.08,'weight_order_flow':0.08,
            'weight_direction':0.08,'weight_market':0.08,
        }
        for name,span in spans.items():
            setattr(p,name,getattr(p,name)+self.random.uniform(-span,span))
        return p.clamp()

    def _crossover(self,a:OptimizationParams,b:OptimizationParams)->OptimizationParams:
        data={}
        frozen = {'main_confidence','main_entry','main_risk_max','main_rr_min'}
        for name in OptimizationParams.__dataclass_fields__:
            if name in frozen:
                data[name] = getattr(a, name)
            else:
                alpha=self.random.random()
                data[name]=alpha*getattr(a,name)+(1-alpha)*getattr(b,name)
        return OptimizationParams(**data).clamp()

    def _mutate(self,p:OptimizationParams)->OptimizationParams:
        data=asdict(p)
        scales={
            'shadow_confidence':2.5,'shadow_entry':2.5,'shadow_risk_max':3.0,'shadow_rr_min':0.12,
            'weight_timing':0.035,'weight_entry':0.035,'weight_order_flow':0.035,
            'weight_direction':0.035,'weight_market':0.035,
        }
        for name,scale in scales.items():
            if self.random.random()<self.mutation_rate:
                data[name]+=self.random.gauss(0,scale)
        return OptimizationParams(**data).clamp()


    @classmethod
    def _lab_breakdown(
        cls,
        rows: list[ClosedTrade],
    ) -> dict:
        main = [row for row in rows if row.lab == "MAIN"]
        shadow = [row for row in rows if row.lab != "MAIN"]
        return {
            "MAIN": cls._stats(main),
            "SHADOW": cls._stats(shadow),
        }

    def optimize(self, progress_callback=None, cancel_check=None) -> dict:
        rows=self._load_closed()
        if len(rows)<self.min_closed:
            return {
                'status':'INSUFFICIENT_QUALITY_DATA','closed':len(rows),
                'total_closed':self._last_training_audit.get('total_closed', len(rows)),
                'required':self.min_closed,
                'training_audit':dict(self._last_training_audit),
                'message':(
                    f'Cần ít nhất {self.min_closed} PAPER samples đạt FULL + '
                    f'VALIDATED + STABLE; hiện có {len(rows)}.'
                ),
            }
        train, validation = self._chronological_split(
            rows,
            self.validation_ratio,
        )
        base=self._base_params()
        self.clear_runtime_cache()
        started_at=time.perf_counter()
        history=[]
        population=[base]+[self._random_params(base) for _ in range(self.population_size-1)]
        best=None
        for generation in range(1,self.generations+1):
            if cancel_check and cancel_check():
                self.clear_runtime_cache()
                return {
                    'status':'CANCELLED',
                    'closed':len(rows),
                    'generation':generation-1,
                    'message':'Quantum optimizer đã được dừng.',
                }
            scored=sorted(
                ((self._score(train,p)[0],p) for p in population),
                key=lambda x:x[0],
                reverse=True,
            )
            elite=[p for _,p in scored[:max(3,self.population_size//10)]]
            if best is None or scored[0][0]>best[0]:
                best=scored[0]
            best_fitness=float(scored[0][0])
            avg_fitness=sum(float(x[0]) for x in scored)/max(len(scored),1)
            elapsed=max(time.perf_counter()-started_at,1e-9)
            info={
                'generation':generation,
                'generations':self.generations,
                'best_fitness':best_fitness,
                'avg_fitness':avg_fitness,
                'elapsed_seconds':elapsed,
                'evaluations':generation*self.population_size,
                'cache_entries':len(self._fitness_cache),
                'population_size':self.population_size,
            }
            history.append(dict(info))
            if progress_callback:
                progress_callback(info)
            pool=[p for _,p in scored[:max(12,self.population_size//3)]]
            next_population=list(elite)
            while len(next_population)<self.population_size:
                next_population.append(
                    self._mutate(
                        self._crossover(
                            self.random.choice(pool),
                            self.random.choice(pool),
                        )
                    )
                )
            population.clear()
            scored.clear()
            pool.clear()
            population=next_population
            if generation % self.gc_every_generations == 0:
                gc.collect()
        best_score,best_params=best
        base_train_score,base_train=self._score(train,base)
        base_val_score,base_val=self._score(validation,base)
        opt_train_score,opt_train=self._score(train,best_params)
        opt_val_score,opt_val=self._score(validation,best_params)
        validation_improvement = opt_val_score - base_val_score
        search_penalty = self._search_penalty()
        required_improvement = (
            self.min_validation_improvement
            + search_penalty
        )
        validation_sample_floor = max(
            self.min_validation_selected,
            int(len(validation) * 0.20),
        )
        avg_r_ok = (
            opt_val['avg_r']
            >= base_val['avg_r']
        )
        drawdown_ok = (
            opt_val['max_dd']
            <= base_val['max_dd']
            + self.max_validation_dd_increase
        )
        stable = (
            opt_val['n'] >= validation_sample_floor
            and validation_improvement
                >= required_improvement
            and avg_r_ok
            and drawdown_ok
        )
        result={
            'status':'RECOMMENDATION' if stable else 'NO_STABLE_IMPROVEMENT',
            'generated_at':datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            'closed':len(rows),
            'total_closed':self._last_training_audit.get('total_closed', len(rows)),
            'training_audit':dict(self._last_training_audit),
            'train_count':len(train),'validation_count':len(validation),
            'base_params':asdict(base),'best_params':asdict(best_params),
            'base_train':base_train,'optimized_train':opt_train,
            'base_validation':base_val,'optimized_validation':opt_val,
            'raw_lab_breakdown': self._lab_breakdown(rows),
            'train_lab_breakdown': self._lab_breakdown(train),
            'validation_lab_breakdown': self._lab_breakdown(validation),
            'validation_improvement': validation_improvement,
            'search_penalty': search_penalty,
            'required_validation_improvement': required_improvement,
            'validation_sample_floor': validation_sample_floor,
            'validation_avg_r_ok': avg_r_ok,
            'validation_drawdown_ok': drawdown_ok,
            'safe_to_apply_shadow': bool(stable),
            'generation_history':history,
            'runtime_seconds':time.perf_counter()-started_at,
            'population_size':self.population_size,
            'generations':self.generations,
            'fitness_cache_peak':max(
                (item['cache_entries'] for item in history),
                default=0,
            ),
            'limitations':[
                'Chỉ tối ưu trên các lệnh Paper đã thực sự được mở và đóng.',
                'Không thể biết kết quả của tín hiệu từng bị loại; vì vậy hạ ngưỡng là counterfactual chưa được quan sát.',
                'Trọng số nội bộ và ranh giới maturity cần Decision Snapshot/Replay đầy đủ mới tối ưu đáng tin cậy.',
                'SHADOW chủ đích thu thập mẫu biên, gồm cả SETUP muộn; không được diễn giải kết quả SHADOW như hiệu suất MAIN.',
            ],
        }
        self.clear_runtime_cache()
        return result

    def save_report(self,result:dict,path:str='data/quantum_optimizer_report.json')->Path:
        target=Path(path); target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return target

    def create_shadow_candidate(
        self,
        result: dict,
        path: str = "data/quantum_shadow_candidate.json",
    ) -> dict:
        """Create a reviewable SHADOW proposal without mutating MAIN config."""
        if not result.get("safe_to_apply_shadow"):
            raise ValueError("Kết quả validation chưa đủ ổn định để tạo Shadow candidate.")
        raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        best = result["best_params"]
        candidate = {}
        changes = {}
        for key in (
            "shadow_confidence",
            "shadow_entry",
            "shadow_risk_max",
            "shadow_rr_min",
        ):
            old = float(raw.get(key, 0))
            proposed = float(best[key])
            max_delta = 2.0 if key != "shadow_rr_min" else 0.10
            bounded = round(max(old-max_delta, min(old+max_delta, proposed)), 4)
            candidate[key] = bounded
            changes[key] = {"old": old, "proposed": bounded}
        forbidden = sorted(key for key in best if str(key).startswith("main_"))
        configured = dict(raw.get("evidence_fusion_family_weights", {}) or {})
        defaults = OptimizationParams()
        fusion_weights = {
            "TIMING": float(best.get("weight_timing", configured.get("TIMING", defaults.weight_timing))),
            "ENTRY": float(best.get("weight_entry", configured.get("ENTRY", defaults.weight_entry))),
            "ORDER_FLOW": float(best.get("weight_order_flow", configured.get("ORDER_FLOW", defaults.weight_order_flow))),
            "DIRECTION": float(best.get("weight_direction", configured.get("DIRECTION", defaults.weight_direction))),
            "MARKET": float(best.get("weight_market", configured.get("MARKET", defaults.weight_market))),
        }
        # Project proposal onto the safe simplex instead of failing the whole
        # review artifact. This is a candidate guardrail, not automatic apply.
        fusion_weights = {k: max(0.05, float(v)) for k, v in fusion_weights.items()}
        fusion_weights["ORDER_FLOW"] = min(0.40, fusion_weights["ORDER_FLOW"])
        total = sum(fusion_weights.values()) or 1.0
        fusion_weights = {k: v / total for k, v in fusion_weights.items()}
        if fusion_weights["ORDER_FLOW"] > 0.40:
            excess = fusion_weights["ORDER_FLOW"] - 0.40
            fusion_weights["ORDER_FLOW"] = 0.40
            others = [k for k in fusion_weights if k != "ORDER_FLOW"]
            denom = sum(fusion_weights[k] for k in others) or 1.0
            for k in others:
                fusion_weights[k] += excess * fusion_weights[k] / denom
        total = sum(fusion_weights.values()) or 1.0
        fusion_weights = {k: round(v / total, 6) for k, v in fusion_weights.items()}
        payload = {
            "schema": "DVS_QUANTUM_SHADOW_CANDIDATE_V2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_report_status": result.get("status"),
            "training_audit": result.get("training_audit", {}),
            "candidate": candidate,
            "evidence_fusion_family_weights": fusion_weights,
            "changes": changes,
            "human_approval_required": True,
            "main_config_mutated": False,
            "main_optimization_blocked": True,
            "rejected_main_keys": forbidden,
        }
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        payload["path"] = str(target)
        return payload

    def apply_shadow_only(self, result: dict, backup: bool = True) -> dict:
        raise RuntimeError(
            "Direct config mutation is disabled in Alpha 2.26.8. "
            "Use create_shadow_candidate() and review it manually."
        )
