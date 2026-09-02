from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .shadow_statistical_comparison import ShadowStatisticalComparison


@dataclass(frozen=True)
class ReadinessResult:
    state: str
    reasons: tuple[str, ...]
    samples: int
    regime_coverage: dict[str, int]
    metrics: dict[str, float]


@dataclass(frozen=True)
class AppendObservationResult:
    observation_id: int
    created: bool
    deduplicated: bool
    observation_key: str


class ShadowObservationStore:
    """Append-only paired Baseline/SHADOW observation store. No order placement."""

    def __init__(self, db_path: str = "data/dvs_paper_trades.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS shadow_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    baseline_decision TEXT NOT NULL,
                    shadow_decision TEXT NOT NULL,
                    baseline_score REAL NOT NULL,
                    shadow_score REAL NOT NULL,
                    paper_trade_id INTEGER,
                    outcome_r REAL,
                    outcome_result TEXT,
                    closed_at TEXT,
                    truth_json TEXT NOT NULL
                )
            """)
            columns={row[1] for row in conn.execute("PRAGMA table_info(shadow_observations)").fetchall()}
            for name, ddl in {
                "paper_trade_id":"INTEGER", "outcome_result":"TEXT", "closed_at":"TEXT"
            }.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE shadow_observations ADD COLUMN {name} {ddl}")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_shadow_observation_trade ON shadow_observations(paper_trade_id) WHERE paper_trade_id IS NOT NULL")
            if "observation_key" not in columns:
                conn.execute("ALTER TABLE shadow_observations ADD COLUMN observation_key TEXT")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS shadow_observation_duplicate_archive (
                    archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    archived_at TEXT NOT NULL,
                    observation_key TEXT NOT NULL,
                    kept_id INTEGER NOT NULL,
                    removed_id INTEGER NOT NULL,
                    removed_row_json TEXT NOT NULL,
                    reason TEXT NOT NULL
                )
            """)
            self._migrate_observation_keys(conn)
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_shadow_observation_key
                ON shadow_observations(observation_key)
                WHERE observation_key IS NOT NULL
            """)

    @staticmethod
    def _canonical_key_payload(*, created_at: str, candidate_id: str, symbol: str,
                               direction: str, regime: str, baseline_decision: str,
                               shadow_decision: str, baseline_score: float,
                               shadow_score: float, truth_json: str) -> dict[str, Any]:
        try:
            truth = json.loads(truth_json or "{}")
        except Exception:
            truth = {}
        # generated_at is the source event time and must remain part of identity.
        return {
            "created_at": str(created_at),
            "candidate_id": str(candidate_id),
            "symbol": str(symbol),
            "direction": str(direction).upper(),
            "regime": str(regime).upper(),
            "baseline_decision": str(baseline_decision).upper(),
            "shadow_decision": str(shadow_decision).upper(),
            "baseline_score": format(float(baseline_score), ".12g"),
            "shadow_score": format(float(shadow_score), ".12g"),
            "truth": truth if isinstance(truth, dict) else {},
        }

    @classmethod
    def observation_key(cls, **kwargs) -> str:
        payload = cls._canonical_key_payload(**kwargs)
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _migrate_observation_keys(self, conn) -> None:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(shadow_observations)")]
        rows = conn.execute(
            "SELECT " + ",".join(columns) + " FROM shadow_observations ORDER BY id"
        ).fetchall()
        if not rows:
            return
        idx = {name: pos for pos, name in enumerate(columns)}
        grouped: dict[str, list[tuple]] = {}
        for row in rows:
            key = row[idx.get("observation_key")] if "observation_key" in idx else None
            if not key:
                key = self.observation_key(
                    created_at=row[idx["created_at"]], candidate_id=row[idx["candidate_id"]],
                    symbol=row[idx["symbol"]], direction=row[idx["direction"]],
                    regime=row[idx["regime"]], baseline_decision=row[idx["baseline_decision"]],
                    shadow_decision=row[idx["shadow_decision"]], baseline_score=row[idx["baseline_score"]],
                    shadow_score=row[idx["shadow_score"]], truth_json=row[idx["truth_json"]],
                )
                conn.execute("UPDATE shadow_observations SET observation_key=? WHERE id=?", (key, row[idx["id"]]))
            grouped.setdefault(str(key), []).append(row)
        archived_at = datetime.now(timezone.utc).isoformat()
        for key, duplicates in grouped.items():
            if len(duplicates) < 2:
                continue
            # Keep the row carrying the most complete linkage/outcome; tie-break on lowest id.
            def rank(row):
                return (
                    int(row[idx["outcome_r"]] is not None),
                    int(row[idx["paper_trade_id"]] is not None),
                    int(row[idx["closed_at"]] is not None),
                    -int(row[idx["id"]]),
                )
            keeper = max(duplicates, key=rank)
            kept_id = int(keeper[idx["id"]])
            for row in duplicates:
                removed_id = int(row[idx["id"]])
                if removed_id == kept_id:
                    continue
                # Merge any missing linkage/outcome into the canonical row before archiving.
                conn.execute("""
                    UPDATE shadow_observations
                    SET paper_trade_id=COALESCE(paper_trade_id, ?),
                        outcome_r=COALESCE(outcome_r, ?),
                        outcome_result=COALESCE(outcome_result, ?),
                        closed_at=COALESCE(closed_at, ?)
                    WHERE id=?
                """, (row[idx["paper_trade_id"]], row[idx["outcome_r"]],
                          row[idx["outcome_result"]], row[idx["closed_at"]], kept_id))
                payload = {name: row[pos] for name, pos in idx.items()}
                conn.execute("""
                    INSERT INTO shadow_observation_duplicate_archive
                    (archived_at,observation_key,kept_id,removed_id,removed_row_json,reason)
                    VALUES (?,?,?,?,?,?)
                """, (archived_at, key, kept_id, removed_id,
                          json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
                          "canonical_observation_key_duplicate"))
                conn.execute("DELETE FROM shadow_observations WHERE id=?", (removed_id,))

    def schema_diagnostics(self) -> dict[str, Any]:
        with self._connect() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(shadow_observations)").fetchall()}
            indexes = {row[1] for row in conn.execute("PRAGMA index_list(shadow_observations)").fetchall()}
            raw = conn.execute("SELECT COUNT(*) FROM shadow_observations").fetchone()[0]
            unique_keys = conn.execute("SELECT COUNT(DISTINCT observation_key) FROM shadow_observations WHERE observation_key IS NOT NULL").fetchone()[0]
            archived = conn.execute("SELECT COUNT(*) FROM shadow_observation_duplicate_archive").fetchone()[0]
        return {
            "db_path": str(self.db_path.resolve()),
            "observation_key_column": "observation_key" in columns,
            "unique_index": "idx_shadow_observation_key" in indexes,
            "rows": int(raw),
            "unique_keys": int(unique_keys),
            "duplicates_archived": int(archived),
            "timestamp_storage": "UTC_ISO8601_FOR_NEW_ROWS",
        }

    def _connect(self):
        return sqlite3.connect(str(self.db_path))

    def append_with_status(self, *, candidate_id: str, symbol: str, direction: str, regime: str,
                           baseline_decision: str, shadow_decision: str, baseline_score: float,
                           shadow_score: float, truth: dict | None = None,
                           created_at: str | None = None,
                           idempotency_key: str | None = None) -> AppendObservationResult:
        payload = json.dumps(dict(truth or {}), ensure_ascii=False, sort_keys=True)
        stamp = created_at or datetime.now(timezone.utc).isoformat()
        key = None
        if idempotency_key:
            canonical = json.dumps({
                "idempotency_key": str(idempotency_key),
                "candidate_id": str(candidate_id),
                "symbol": str(symbol),
                "direction": str(direction).upper(),
            }, sort_keys=True, separators=(",", ":"))
            key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            cur = conn.execute("""
                INSERT OR IGNORE INTO shadow_observations
                (created_at,candidate_id,symbol,direction,regime,baseline_decision,shadow_decision,
                 baseline_score,shadow_score,paper_trade_id,outcome_r,outcome_result,closed_at,truth_json,observation_key)
                VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,?,?)
            """, (stamp, candidate_id, symbol, direction, regime, baseline_decision, shadow_decision,
                      float(baseline_score), float(shadow_score), payload, key))
            if cur.rowcount == 1:
                oid = int(cur.lastrowid)
                return AppendObservationResult(oid, True, False, key)
            row = conn.execute("SELECT id FROM shadow_observations WHERE observation_key=?", (key,)).fetchone() if key else None
            if row is None:
                raise RuntimeError("observation insert ignored without canonical row")
            return AppendObservationResult(int(row[0]), False, True, key)

    def append(self, **kwargs) -> int:
        return self.append_with_status(**kwargs).observation_id

    def bind_trade(self, observation_id: int, paper_trade_id: int) -> bool:
        with self._connect() as conn:
            cur=conn.execute("UPDATE shadow_observations SET paper_trade_id=? WHERE id=? AND paper_trade_id IS NULL",
                             (int(paper_trade_id), int(observation_id)))
            return cur.rowcount == 1

    def close_outcome(self, observation_id: int, outcome_r: float, *, result: str = "CLOSED", closed_at: str | None = None) -> bool:
        stamp=closed_at or datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur=conn.execute("UPDATE shadow_observations SET outcome_r=?,outcome_result=?,closed_at=? WHERE id=? AND outcome_r IS NULL",
                         (float(outcome_r), str(result), stamp, int(observation_id)))
            return cur.rowcount == 1

    def close_for_trade(self, paper_trade_id: int, outcome_r: float, *, result: str = "CLOSED", closed_at: str | None = None) -> bool:
        stamp=closed_at or datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur=conn.execute("UPDATE shadow_observations SET outcome_r=?,outcome_result=?,closed_at=? WHERE paper_trade_id=? AND outcome_r IS NULL",
                         (float(outcome_r), str(result), stamp, int(paper_trade_id)))
            return cur.rowcount == 1

    def rows(self, candidate_id: str, *, closed_only: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT id,created_at,symbol,direction,regime,baseline_decision,shadow_decision,baseline_score,shadow_score,paper_trade_id,outcome_r,outcome_result,closed_at,truth_json FROM shadow_observations WHERE candidate_id=?"
        if closed_only:
            sql += " AND outcome_r IS NOT NULL"
        sql += " ORDER BY id"
        with self._connect() as conn:
            result=conn.execute(sql,(candidate_id,)).fetchall()
        keys=("id","created_at","symbol","direction","regime","baseline_decision","shadow_decision","baseline_score","shadow_score","paper_trade_id","outcome_r","outcome_result","closed_at","truth_json")
        return [dict(zip(keys,row)) for row in result]

    def all_rows(self, candidate_id: str) -> list[dict[str, Any]]:
        return self.rows(candidate_id, closed_only=False)


class PromotionReadinessAudit:
    """Observe-only readiness judgement; never applies or promotes configuration."""

    def __init__(self, *, min_samples: int = 60, min_regime_samples: int = 12,
                 min_expectancy_delta: float = 0.0, max_regime_underperformance: float = -0.15,
                 statistical_min_samples: int = 40, minimum_detectable_improvement: float = 0.03) -> None:
        self.min_samples=max(1,int(min_samples)); self.min_regime_samples=max(1,int(min_regime_samples))
        self.min_expectancy_delta=float(min_expectancy_delta)
        self.max_regime_underperformance=float(max_regime_underperformance)
        self.statistical = ShadowStatisticalComparison(
            min_samples=max(10, int(statistical_min_samples)),
            minimum_detectable_improvement=max(0.0, float(minimum_detectable_improvement)),
        )

    @staticmethod
    def _selected(decision: str) -> bool:
        return str(decision).upper() in {"READY","SETUP","RUNNING","TRADE"}

    def evaluate(self, rows: list[dict[str, Any]], *, quality_result=None) -> ReadinessResult:
        if quality_result is not None:
            if getattr(quality_result, "state", "BLOCKED") == "BLOCKED":
                return ReadinessResult("INSUFFICIENT_DATA", tuple(getattr(quality_result,"reasons",()) or ("observation quality blocked",)), 0, {}, {"observation_quality":0.0})
            rows=list(getattr(quality_result,"eligible_rows",()) or ())
        closed=[r for r in rows if r.get("outcome_r") is not None]
        coverage: dict[str,int]={}
        for row in closed: coverage[str(row.get("regime") or "UNKNOWN").upper()]=coverage.get(str(row.get("regime") or "UNKNOWN").upper(),0)+1
        if len(closed)<self.min_samples:
            return ReadinessResult("INSUFFICIENT_DATA",(f"samples {len(closed)} < {self.min_samples}",),len(closed),coverage,{})
        base=[float(r["outcome_r"]) for r in closed if self._selected(r.get("baseline_decision",""))]
        shadow=[float(r["outcome_r"]) for r in closed if self._selected(r.get("shadow_decision",""))]
        base_exp=sum(base)/len(base) if base else 0.0; shadow_exp=sum(shadow)/len(shadow) if shadow else 0.0
        delta=shadow_exp-base_exp
        statistical=self.statistical.compare(closed)
        reasons=list(statistical.reasons) if statistical.state != "INSUFFICIENT_DATA" else [f"expectancy_delta={delta:+.4f}"]
        unstable=False
        for regime,count in coverage.items():
            if count<self.min_regime_samples: continue
            rr=[r for r in closed if str(r.get("regime") or "UNKNOWN").upper()==regime]
            b=[float(r["outcome_r"]) for r in rr if self._selected(r.get("baseline_decision",""))]
            s=[float(r["outcome_r"]) for r in rr if self._selected(r.get("shadow_decision",""))]
            d=(sum(s)/len(s) if s else 0.0)-(sum(b)/len(b) if b else 0.0)
            if d<self.max_regime_underperformance: unstable=True; reasons.append(f"{regime}_delta={d:+.4f}")
        if unstable or statistical.state == "UNSTABLE":
            state="CANDIDATE_UNSTABLE"
        elif statistical.state == "WORSE" or delta<self.min_expectancy_delta:
            state="CANDIDATE_UNDERPERFORMS"
        elif statistical.state == "INCONCLUSIVE":
            state="CONTINUE_OBSERVATION"
        elif any(v<self.min_regime_samples for v in coverage.values()) or len(coverage)<2:
            state="CONTINUE_OBSERVATION"
        else:
            state="READY_FOR_NEXT_REVIEW"
        metrics={"baseline_expectancy":base_exp,"shadow_expectancy":shadow_exp,"expectancy_delta":delta}
        if statistical.state != "INSUFFICIENT_DATA":
            metrics.update({"ci_low":statistical.ci_low,"ci_high":statistical.ci_high,
                            "probability_improvement":statistical.probability_improvement,
                            "minimum_detectable_improvement":statistical.minimum_detectable_improvement,
                            "stable_block_ratio":statistical.stable_block_ratio})
        return ReadinessResult(state,tuple(reasons),len(closed),coverage,metrics)


class ShadowObservationRuntime:
    """Runtime bridge for paired MAIN/SHADOW PAPER observations. Evidence-only."""

    def __init__(self, store: ShadowObservationStore | None = None, *, data_dir: str = "data", promotion_dir: str = "data/shadow_promotions") -> None:
        self.store=store or ShadowObservationStore()
        self.data_dir=Path(data_dir); self.promotion_dir=Path(promotion_dir)
        self._stats={"attempted":0,"recorded":0,"deduplicated":0,"bound":0,"closed":0,"errors":0}
        from .historical_snapshot_runtime import HistoricalSnapshotRuntime
        self.snapshot_runtime=HistoricalSnapshotRuntime(observation_store=self.store)

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            value=json.loads(path.read_text(encoding="utf-8")); return value if isinstance(value,dict) else {}
        except Exception:
            return {}

    def active_candidate_id(self) -> str:
        audits=sorted(self.promotion_dir.glob("promotion_*.json"), reverse=True) if self.promotion_dir.exists() else []
        if audits:
            payload=self._read_json(audits[0])
            return str(payload.get("candidate_id") or payload.get("candidate_schema") or audits[0].stem)
        candidate=self._read_json(self.data_dir / "quantum_shadow_candidate.json")
        return str(candidate.get("candidate_id") or "CURRENT_SHADOW_BASELINE")

    def record_pair(self, analysis, *, direction: str, main_ok: bool, shadow_ok: bool, main_reasons=(), shadow_reasons=()) -> int | None:
        try:
            confidence=float(getattr(analysis,"confidence_score",0.0) or 0.0)
            entry=float(getattr(getattr(analysis,"smart_entry",None),"entry_score",0.0) or 0.0)
            truth={
                "schema":"DVS_SHADOW_OBSERVATION_V1",
                "generated_at":str(getattr(analysis,"generated_at","")),
                "confidence":confidence, "entry_score":entry,
                "main_reasons":list(main_reasons), "shadow_reasons":list(shadow_reasons),
                "calibration_state":str(getattr(analysis,"probability_calibration_state","NOT_EVALUATED")),
                "drift_state":str(getattr(analysis,"calibration_drift_state","INSUFFICIENT_DATA")),
                "evidence_snapshot":getattr(analysis,"evidence_reliability_summary",()),
                "calibrated_probability":float(getattr(analysis,"calibrated_probability",0.0) or 0.0),
                "adaptive_probability":float(getattr(analysis,"adaptive_probability",0.0) or 0.0),
                "evidence_reliability":float(getattr(analysis,"evidence_reliability_score",0.0) or 0.0),
            }
            self._stats["attempted"] += 1
            result=self.store.append_with_status(
                candidate_id=self.active_candidate_id(), symbol=str(getattr(analysis,"symbol","UNKNOWN")),
                direction=str(direction).upper(), regime=str(getattr(getattr(analysis,"regime",None),"regime","UNKNOWN")),
                baseline_decision="READY" if main_ok else "WAIT", shadow_decision="READY" if shadow_ok else "WAIT",
                baseline_score=confidence, shadow_score=confidence, truth=truth,
                created_at=str(getattr(analysis,"generated_at","") or datetime.now(timezone.utc).isoformat()),
                idempotency_key=str(
                    getattr(analysis, "analysis_id", "")
                    or getattr(analysis, "scan_id", "")
                    or f"{getattr(analysis, 'generated_at', '')}|{getattr(analysis, 'symbol', 'UNKNOWN')}|{str(direction).upper()}"
                ),
            )
            if result.created:
                self._stats["recorded"] += 1
            if result.deduplicated:
                self._stats["deduplicated"] += 1
            return result.observation_id
        except Exception:
            self._stats["errors"]+=1; return None

    def bind_trade(self, observation_id: int | None, paper_trade_id: int | None) -> bool:
        if not observation_id or not paper_trade_id: return False
        try:
            ok=self.store.bind_trade(observation_id,paper_trade_id)
            if ok: self._stats["bound"]+=1
            return ok
        except Exception:
            self._stats["errors"]+=1; return False

    def close_trade(self, paper_trade_id: int, outcome_r: float, *, result: str, closed_at: str | None = None) -> bool:
        try:
            ok=self.store.close_for_trade(paper_trade_id,outcome_r,result=result,closed_at=closed_at)
            if ok:
                self._stats["closed"]+=1
                candidate_id=self.active_candidate_id()
                self.snapshot_runtime.capture(candidate_id)
            return ok
        except Exception:
            self._stats["errors"]+=1; return False

    def diagnostics(self) -> dict:
        candidate_id=self.active_candidate_id()
        quality=ObservationQualityAudit().evaluate(self.store.all_rows(candidate_id))
        return {**self._stats,"candidate_id":candidate_id,"quality_state":quality.state,
                "quality_total":quality.total,"quality_eligible":quality.eligible,
                "bind_rate":quality.bind_rate,"close_rate":quality.close_rate,
                "quality_reasons":quality.reasons,"snapshot_runtime":self.snapshot_runtime.diagnostics(),
                "store_schema":self.store.schema_diagnostics()}


@dataclass(frozen=True)
class ObservationQualityResult:
    state: str
    reasons: tuple[str, ...]
    total: int
    bound: int
    closed: int
    eligible: int
    bind_rate: float
    close_rate: float
    regime_coverage: dict[str, int]
    excluded: dict[str, int]
    eligible_rows: tuple[dict[str, Any], ...]


class ObservationQualityAudit:
    """Fail-closed quality gate for readiness evidence; never mutates observations."""

    def __init__(self, *, min_bind_rate: float = 0.10, min_close_rate: float = 0.60,
                 min_eligible: int = 20, max_age_days: int = 45,
                 required_truth_schema: str = "DVS_SHADOW_OBSERVATION_V1") -> None:
        self.min_bind_rate=max(0.0,min(1.0,float(min_bind_rate)))
        self.min_close_rate=max(0.0,min(1.0,float(min_close_rate)))
        self.min_eligible=max(1,int(min_eligible)); self.max_age_days=max(1,int(max_age_days))
        self.required_truth_schema=str(required_truth_schema)

    @staticmethod
    def _finite(value) -> bool:
        try:
            number=float(value); return number == number and abs(number) != float("inf")
        except (TypeError, ValueError): return False

    @staticmethod
    def _parse_time(value: str):
        try:
            stamp=datetime.fromisoformat(str(value).replace("Z","+00:00"))
            return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
        except Exception: return None

    def evaluate(self, rows: list[dict[str, Any]], *, now: datetime | None = None) -> ObservationQualityResult:
        now=now or datetime.now(timezone.utc); total=len(rows)
        bound=sum(1 for r in rows if r.get("paper_trade_id") is not None)
        closed=sum(1 for r in rows if r.get("outcome_r") is not None)
        bind_rate=bound/total if total else 0.0; close_rate=closed/bound if bound else 0.0
        excluded={"unbound":0,"missing_outcome":0,"invalid_outcome":0,"stale":0,"invalid_truth":0}
        eligible=[]; coverage={}
        for row in rows:
            if row.get("paper_trade_id") is None: excluded["unbound"]+=1; continue
            if row.get("outcome_r") is None: excluded["missing_outcome"]+=1; continue
            if not self._finite(row.get("outcome_r")): excluded["invalid_outcome"]+=1; continue
            stamp=self._parse_time(row.get("closed_at") or row.get("created_at"))
            if stamp is None or (now-stamp).total_seconds() > self.max_age_days*86400:
                excluded["stale"]+=1; continue
            try: truth=json.loads(row.get("truth_json") or "{}")
            except Exception: truth={}
            if not isinstance(truth,dict) or truth.get("schema") != self.required_truth_schema:
                excluded["invalid_truth"]+=1; continue
            regime=str(row.get("regime") or "UNKNOWN").upper()
            coverage[regime]=coverage.get(regime,0)+1; eligible.append(row)
        reasons=[]
        if total == 0: reasons.append("no observations")
        if bind_rate < self.min_bind_rate: reasons.append(f"bind_rate {bind_rate:.3f} < {self.min_bind_rate:.3f}")
        if close_rate < self.min_close_rate: reasons.append(f"close_rate {close_rate:.3f} < {self.min_close_rate:.3f}")
        if len(eligible) < self.min_eligible: reasons.append(f"eligible {len(eligible)} < {self.min_eligible}")
        if total == 0 or bind_rate < self.min_bind_rate or len(eligible) == 0:
            state="BLOCKED"
        elif close_rate < self.min_close_rate or len(eligible) < self.min_eligible:
            state="DEGRADED"
        else:
            state="FULL"
        return ObservationQualityResult(state,tuple(reasons),total,bound,closed,len(eligible),bind_rate,close_rate,coverage,excluded,tuple(eligible))
