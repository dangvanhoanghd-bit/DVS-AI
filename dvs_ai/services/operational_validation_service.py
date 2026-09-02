from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else float(default)
    except (TypeError, ValueError):
        return float(default)


def _state_points(state: str, mapping: Mapping[str, float], default: float) -> float:
    return float(mapping.get(str(state or "").upper(), default))


@dataclass(frozen=True)
class CoverageSnapshot:
    state: str
    total: int
    eligible: int
    regimes: dict[str, int]
    directions: dict[str, int]
    order_flow_quality: dict[str, int]
    regime_coverage: float
    direction_coverage: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ConfidenceSnapshot:
    state: str
    samples: int
    mean: float
    median: float
    p90: float
    p95: float
    acceptance_55: float
    acceptance_70: float
    histogram: dict[str, int]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RegimeMetric:
    regime: str
    samples: int
    baseline_expectancy: float
    shadow_expectancy: float
    delta: float
    state: str


@dataclass(frozen=True)
class RegimeValidationSnapshot:
    state: str
    metrics: tuple[RegimeMetric, ...]
    supported_regimes: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class OperationalAlert:
    severity: str
    code: str
    title: str
    reason: str
    action: str
    impact: str = "Operational evidence may be unreliable."
    composite: bool = False


@dataclass(frozen=True)
class AIHealthSnapshot:
    score: float
    state: str
    contributors: dict[str, float]
    alerts: tuple[OperationalAlert, ...]
    generated_at: str
    next_action: str
    weights: dict[str, float] | None = None
    modifiers: dict[str, float] | None = None
    validation_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class OperationalValidationSnapshot:
    health: AIHealthSnapshot
    coverage: CoverageSnapshot
    confidence: ConfidenceSnapshot
    regimes: RegimeValidationSnapshot


class DataCoverageEngine:
    REQUIRED_REGIMES = ("BULL", "BEAR", "RANGE")
    REQUIRED_DIRECTIONS = ("LONG", "SHORT")

    def __init__(self, *, min_total: int = 60, min_regime: int = 15, min_direction: int = 20):
        self.min_total = max(1, int(min_total))
        self.min_regime = max(1, int(min_regime))
        self.min_direction = max(1, int(min_direction))

    @staticmethod
    def _normalize_regime(value: Any) -> str:
        text = str(value or "UNKNOWN").upper()
        if "BULL" in text or ("TREND" in text and "UP" in text):
            return "BULL"
        if "BEAR" in text or ("TREND" in text and "DOWN" in text):
            return "BEAR"
        if "RANGE" in text or "SIDE" in text:
            return "RANGE"
        if "VOLAT" in text:
            return "VOLATILE"
        return text

    def evaluate(self, rows: Iterable[Mapping[str, Any]]) -> CoverageSnapshot:
        prepared = list(rows or ())
        regimes: dict[str, int] = {}
        directions: dict[str, int] = {}
        qualities: dict[str, int] = {}
        eligible = 0
        for row in prepared:
            regime = self._normalize_regime(row.get("regime"))
            direction = str(row.get("direction") or "UNKNOWN").upper()
            regimes[regime] = regimes.get(regime, 0) + 1
            directions[direction] = directions.get(direction, 0) + 1
            truth = row.get("truth")
            if not isinstance(truth, Mapping):
                try:
                    truth = json.loads(str(row.get("truth_json") or "{}"))
                except Exception:
                    truth = {}
            quality = str((truth or {}).get("order_flow_quality", "UNKNOWN")).upper()
            qualities[quality] = qualities.get(quality, 0) + 1
            if row.get("outcome_r") is not None and row.get("paper_trade_id") is not None:
                eligible += 1

        supported_regimes = sum(regimes.get(name, 0) >= self.min_regime for name in self.REQUIRED_REGIMES)
        supported_directions = sum(directions.get(name, 0) >= self.min_direction for name in self.REQUIRED_DIRECTIONS)
        regime_coverage = supported_regimes / len(self.REQUIRED_REGIMES)
        direction_coverage = supported_directions / len(self.REQUIRED_DIRECTIONS)
        reasons: list[str] = []
        for name in self.REQUIRED_REGIMES:
            if regimes.get(name, 0) < self.min_regime:
                reasons.append(f"{name} {regimes.get(name, 0)}/{self.min_regime}")
        for name in self.REQUIRED_DIRECTIONS:
            if directions.get(name, 0) < self.min_direction:
                reasons.append(f"{name} {directions.get(name, 0)}/{self.min_direction}")
        if eligible < self.min_total:
            reasons.append(f"eligible {eligible}/{self.min_total}")
        if eligible == 0:
            state = "BLOCKED"
        elif eligible < self.min_total or regime_coverage < 2 / 3 or direction_coverage < 1.0:
            state = "DEGRADED"
        else:
            state = "FULL"
        return CoverageSnapshot(
            state, len(prepared), eligible, regimes, directions, qualities,
            regime_coverage, direction_coverage, tuple(reasons),
        )


class ConfidenceDistributionEngine:
    BUCKETS = ((0, 30, "0-30"), (30, 50, "30-50"), (50, 70, "50-70"), (70, 101, "70+"))

    def __init__(self, *, min_samples: int = 100):
        self.min_samples = max(1, int(min_samples))

    @staticmethod
    def _percentile(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        pos = (len(ordered) - 1) * q
        low = int(math.floor(pos)); high = int(math.ceil(pos))
        if low == high:
            return ordered[low]
        return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)

    def evaluate(self, values: Iterable[Any]) -> ConfidenceSnapshot:
        scores = [_finite(value) for value in values]
        scores = [max(0.0, min(100.0, value)) for value in scores]
        histogram = {label: 0 for _, _, label in self.BUCKETS}
        for value in scores:
            for low, high, label in self.BUCKETS:
                if low <= value < high:
                    histogram[label] += 1
                    break
        n = len(scores)
        reasons: list[str] = []
        if n < self.min_samples:
            reasons.append(f"samples {n}/{self.min_samples}")
        acceptance_55 = sum(value >= 55 for value in scores) / n if n else 0.0
        acceptance_70 = sum(value >= 70 for value in scores) / n if n else 0.0
        if n == 0:
            state = "INSUFFICIENT_DATA"
        elif n < self.min_samples:
            state = "LEARNING"
        elif acceptance_70 < 0.005:
            state = "VERY_STRICT"
            reasons.append("<0.5% signals reach 70")
        elif acceptance_70 < 0.02:
            state = "STRICT"
        else:
            state = "BALANCED"
        return ConfidenceSnapshot(
            state=state,
            samples=n,
            mean=sum(scores) / n if n else 0.0,
            median=median(scores) if scores else 0.0,
            p90=self._percentile(scores, 0.90),
            p95=self._percentile(scores, 0.95),
            acceptance_55=acceptance_55,
            acceptance_70=acceptance_70,
            histogram=histogram,
            reasons=tuple(reasons),
        )


class RegimeValidationEngine:
    def __init__(self, *, min_samples: int = 15, underperformance_limit: float = -0.10):
        self.min_samples = max(1, int(min_samples))
        self.underperformance_limit = float(underperformance_limit)

    @staticmethod
    def _selected(value: Any) -> bool:
        return str(value or "").upper() in {"READY", "SETUP", "RUNNING", "TRADE"}

    def evaluate(self, rows: Iterable[Mapping[str, Any]]) -> RegimeValidationSnapshot:
        grouped: dict[str, list[Mapping[str, Any]]] = {}
        normalizer = DataCoverageEngine._normalize_regime
        for row in rows or ():
            if row.get("outcome_r") is None:
                continue
            grouped.setdefault(normalizer(row.get("regime")), []).append(row)
        metrics: list[RegimeMetric] = []
        reasons: list[str] = []
        for regime in sorted(grouped):
            group = grouped[regime]
            base = [_finite(row.get("outcome_r")) for row in group if self._selected(row.get("baseline_decision"))]
            shadow = [_finite(row.get("outcome_r")) for row in group if self._selected(row.get("shadow_decision"))]
            base_exp = sum(base) / len(base) if base else 0.0
            shadow_exp = sum(shadow) / len(shadow) if shadow else 0.0
            delta = shadow_exp - base_exp
            if len(group) < self.min_samples:
                state = "INSUFFICIENT_DATA"
            elif delta < self.underperformance_limit:
                state = "UNDERPERFORMS"
                reasons.append(f"{regime} delta {delta:+.3f}R")
            elif delta > 0.03:
                state = "SUPPORTED"
            else:
                state = "WATCH"
            metrics.append(RegimeMetric(regime, len(group), base_exp, shadow_exp, delta, state))
        supported = sum(metric.state == "SUPPORTED" for metric in metrics)
        if not metrics:
            state = "INSUFFICIENT_DATA"
        elif any(metric.state == "UNDERPERFORMS" for metric in metrics):
            state = "UNSTABLE"
        elif supported >= 2:
            state = "SUPPORTED"
        else:
            state = "CONTINUE_OBSERVATION"
        return RegimeValidationSnapshot(state, tuple(metrics), supported, tuple(reasons))


class OperationalAlertCenter:
    SEVERITY_RANK = {"INFO": 1, "WATCH": 2, "WARNING": 3, "CRITICAL": 4}

    def build(self, *, coverage: CoverageSnapshot, confidence: ConfidenceSnapshot,
              regimes: RegimeValidationSnapshot, calibration_state: str = "UNKNOWN",
              drift_state: str = "UNKNOWN", reliability_state: str = "UNKNOWN",
              runtime_state: str = "UNKNOWN") -> tuple[OperationalAlert, ...]:
        alerts: list[OperationalAlert] = []
        def add(severity: str, code: str, title: str, reason: str, action: str, impact: str) -> None:
            alerts.append(OperationalAlert(severity, code, title, reason, action, impact, False))
        if coverage.state == "BLOCKED":
            add("CRITICAL", "COVERAGE_BLOCKED", "Observation coverage bị khóa",
                "; ".join(coverage.reasons[:4]) or "Không có observation hợp lệ",
                "Tiếp tục PAPER; không đánh giá hoặc promotion Candidate.",
                "Không đủ bằng chứng vận hành để kết luận.")
        elif coverage.state == "DEGRADED":
            add("WARNING", "COVERAGE_DEGRADED", "Coverage chưa đầy đủ",
                "; ".join(coverage.reasons[:4]), "Thu thập thêm dữ liệu tại regime/hướng còn thiếu.",
                "Kết quả có thể thiên lệch theo regime hoặc hướng.")
        drift = str(drift_state).upper()
        if drift == "DRIFT":
            add("CRITICAL", "CALIBRATION_DRIFT", "Calibration đang drift", "Drift monitor = DRIFT",
                "Dừng mọi promotion và tiếp tục quan sát PAPER.", "Xác suất hiệu chỉnh có thể không còn đại diện.")
        elif drift == "WATCH":
            add("WARNING", "CALIBRATION_WATCH", "Calibration cần theo dõi", "Drift monitor = WATCH",
                "Không promotion cho đến khi trở lại STABLE.", "Độ tin cậy của calibrated probability đang suy giảm.")
        if str(calibration_state).upper() not in {"VALIDATED", "STABLE"}:
            add("INFO", "CALIBRATION_NOT_VALIDATED", "Calibration chưa được xác nhận",
                f"Calibration = {calibration_state}", "Tiếp tục tích lũy outcome PAPER.",
                "Chưa đủ bằng chứng để dùng calibration cho review.")
        if str(reliability_state).upper() in {"UNKNOWN", "INSUFFICIENT_DATA"}:
            add("INFO", "RELIABILITY_UNKNOWN", "Evidence reliability chưa đủ mẫu",
                f"Reliability = {reliability_state}", "Tiếp tục thu thập evidence snapshot.",
                "Family reliability chưa được chứng minh.")
        if regimes.state == "UNSTABLE":
            add("CRITICAL", "REGIME_UNSTABLE", "Shadow không ổn định theo regime",
                "; ".join(regimes.reasons) or "Có regime underperform", "Không promotion toàn cục.",
                "Hiệu quả tổng có thể che giấu suy giảm ở một regime.")
        if confidence.state in {"VERY_STRICT", "STRICT"}:
            add("INFO", "CONFIDENCE_STRICT", "Phân bố confidence bảo thủ",
                f"{confidence.acceptance_70 * 100:.2f}% đạt ngưỡng 70",
                "Chưa đổi threshold; tiếp tục kiểm chứng outcome của vùng 50–70.",
                "Tần suất tín hiệu MAIN có thể quá thấp để đánh giá.")
        if str(runtime_state).upper() in {"ERROR", "BLOCKED", "OFFLINE"}:
            add("CRITICAL", "RUNTIME_UNHEALTHY", "Runtime dữ liệu không khỏe",
                f"Runtime = {runtime_state}", "Khắc phục collector/runtime trước khi dùng dữ liệu mới.",
                "Dữ liệu mới có thể thiếu hoặc sai thời điểm.")

        codes = {a.code for a in alerts}
        composite = None
        if "CALIBRATION_DRIFT" in codes and ("COVERAGE_BLOCKED" in codes or "RUNTIME_UNHEALTHY" in codes):
            composite = OperationalAlert("CRITICAL", "COMPOSITE_EVIDENCE_INCIDENT",
                "Critical Evidence Incident", "Calibration drift kết hợp với coverage/runtime bị khóa.",
                "Đóng băng mọi review/promotion; khắc phục dữ liệu rồi chạy lại Truth Audit.",
                "Nhiều lớp bằng chứng đồng thời mất độ tin cậy.", True)
        elif "REGIME_UNSTABLE" in codes and "COVERAGE_DEGRADED" in codes:
            composite = OperationalAlert("CRITICAL", "COMPOSITE_REGIME_INCIDENT",
                "Regime Validation Incident", "Regime underperformance xuất hiện khi coverage chưa đầy đủ.",
                "Tiếp tục PAPER theo regime thiếu; không promotion toàn cục.",
                "Kết luận regime có nguy cơ không ổn định và thiếu đại diện.", True)
        elif "COVERAGE_DEGRADED" in codes and "CONFIDENCE_STRICT" in codes:
            composite = OperationalAlert("WATCH", "COMPOSITE_DATA_WATCH",
                "Data Accumulation Watch", "Coverage thấp đồng thời confidence rất bảo thủ.",
                "Duy trì Auto PAPER; chưa thay threshold; theo dõi observation velocity.",
                "Tốc độ tích lũy bằng chứng có thể chậm.", True)
        if composite is not None:
            alerts.insert(0, composite)
        return tuple(sorted(alerts, key=lambda a: (-self.SEVERITY_RANK.get(a.severity, 0), not a.composite, a.code)))


class AIHealthService:
    DEFAULT_WEIGHTS = {
        "data_quality": 20.0, "calibration": 18.0, "reliability": 17.0,
        "coverage": 20.0, "regime_stability": 15.0, "runtime": 10.0,
    }
    DEFAULT_MODIFIERS = {
        "BULL": {"calibration": 1.10},
        "BEAR": {"reliability": 1.15},
        "RANGE": {"coverage": 1.20},
        "VOLATILE": {"runtime": 1.30, "data_quality": 1.20},
    }

    def __init__(self, db_path: str = "data/dvs_paper_trades.db", *, weights=None, regime_modifiers=None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.weights, self.weight_warnings = self._validate_weights(weights)
        self.regime_modifiers, modifier_warnings = self._validate_modifiers(regime_modifiers)
        self.weight_warnings += modifier_warnings
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS ai_health_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT, generated_at TEXT NOT NULL, score REAL NOT NULL,
                state TEXT NOT NULL, contributors_json TEXT NOT NULL, alerts_json TEXT NOT NULL,
                snapshot_key TEXT NOT NULL UNIQUE)""")

    @classmethod
    def _validate_weights(cls, raw):
        warnings=[]
        if not isinstance(raw, Mapping):
            return dict(cls.DEFAULT_WEIGHTS), ("health_weights missing; defaults used",)
        clean={}
        for key, default in cls.DEFAULT_WEIGHTS.items():
            value=_finite(raw.get(key), default)
            if value < 1 or value > 50:
                warnings.append(f"{key} out of range; default used")
                value=default
            clean[key]=value
        total=sum(clean.values())
        if total <= 0:
            return dict(cls.DEFAULT_WEIGHTS), tuple(warnings+["invalid total; defaults used"])
        normalized={k: v*100.0/total for k,v in clean.items()}
        if abs(total-100.0)>1e-6:
            warnings.append(f"weights normalized from {total:.2f} to 100")
        return normalized, tuple(warnings)

    @classmethod
    def _validate_modifiers(cls, raw):
        if not isinstance(raw, Mapping):
            return {k:dict(v) for k,v in cls.DEFAULT_MODIFIERS.items()}, ("regime modifiers missing; defaults used",)
        clean={}; warnings=[]
        for regime, values in raw.items():
            regime=str(regime).upper()
            if regime not in {"BULL","BEAR","RANGE","VOLATILE"} or not isinstance(values, Mapping):
                warnings.append(f"invalid regime modifier {regime}"); continue
            clean[regime]={}
            for key,val in values.items():
                if key not in cls.DEFAULT_WEIGHTS: continue
                number=_finite(val,1.0)
                if number < 0.75 or number > 1.50:
                    warnings.append(f"modifier {regime}.{key} out of range; ignored"); continue
                clean[regime][key]=number
        return clean, tuple(warnings)

    def evaluate(self, *, coverage: CoverageSnapshot, confidence: ConfidenceSnapshot,
                 regimes: RegimeValidationSnapshot, alerts: tuple[OperationalAlert, ...],
                 calibration_state: str = "UNKNOWN", drift_state: str = "UNKNOWN",
                 reliability_state: str = "UNKNOWN", runtime_state: str = "UNKNOWN",
                 active_regime: str = "UNKNOWN") -> AIHealthSnapshot:
        fractions={
            "data_quality": _state_points(runtime_state,{"CONNECTED":1,"FULL":1,"DEGRADED":.6,"CONNECTING":.5,"DISABLED":.35,"ERROR":0,"BLOCKED":0},.35),
            "calibration": min(_state_points(calibration_state,{"VALIDATED":1,"STABLE":1,"WATCH":.55,"INSUFFICIENT_DATA":.35,"NOT_EVALUATED":.3},.3), _state_points(drift_state,{"STABLE":1,"WATCH":.55,"DRIFT":0,"INSUFFICIENT_DATA":.35,"NOT_EVALUATED":.3},.3)),
            "reliability": _state_points(reliability_state,{"VALIDATED":1,"SHRUNK":.7,"UNKNOWN":.35,"INSUFFICIENT_DATA":.35},.35),
            "coverage": _state_points(coverage.state,{"FULL":1,"DEGRADED":.55,"BLOCKED":0},0),
            "regime_stability": _state_points(regimes.state,{"SUPPORTED":1,"CONTINUE_OBSERVATION":.55,"INSUFFICIENT_DATA":.35,"UNSTABLE":0},.35),
            "runtime": _state_points(runtime_state,{"CONNECTED":1,"FULL":1,"CONNECTING":.6,"BACKOFF":.4,"DISABLED":.35,"ERROR":0},.35),
        }
        active=str(active_regime or "UNKNOWN").upper()
        modifiers={k:1.0 for k in self.weights}
        modifiers.update(self.regime_modifiers.get(active,{}))
        effective={k:self.weights[k]*modifiers[k] for k in self.weights}
        scale=100.0/sum(effective.values()) if sum(effective.values()) else 1.0
        contributors={k:effective[k]*scale*fractions[k] for k in self.weights}
        score=max(0,min(100,sum(contributors.values())))
        critical=any(a.severity=="CRITICAL" for a in alerts)
        state="CRITICAL" if critical or score<45 else "WATCH" if score<70 else "STABLE" if score<85 else "HEALTHY"
        next_action=alerts[0].action if alerts else ("Tiếp tục chạy PAPER để hoàn thiện coverage." if coverage.state!="FULL" else "Tiếp tục quan sát; chưa có hành động khẩn cấp.")
        return AIHealthSnapshot(round(score,2),state,contributors,alerts,datetime.now(timezone.utc).isoformat(),next_action,dict(self.weights),modifiers,tuple(self.weight_warnings))

    def append(self, snapshot: AIHealthSnapshot, *, snapshot_key: str | None = None) -> bool:
        key=snapshot_key or f"{snapshot.generated_at[:16]}:{snapshot.state}:{round(snapshot.score,1)}"
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("INSERT INTO ai_health_history(generated_at,score,state,contributors_json,alerts_json,snapshot_key) VALUES(?,?,?,?,?,?)",(snapshot.generated_at,snapshot.score,snapshot.state,json.dumps(snapshot.contributors,sort_keys=True),json.dumps([asdict(a) for a in snapshot.alerts],sort_keys=True),key))
            return True
        except sqlite3.IntegrityError: return False

    def recent(self, limit: int = 100):
        with sqlite3.connect(str(self.db_path)) as conn:
            rows=conn.execute("SELECT generated_at,score,state,contributors_json,alerts_json FROM ai_health_history ORDER BY id DESC LIMIT ?",(max(1,int(limit)),)).fetchall()
        return [{"generated_at":r[0],"score":r[1],"state":r[2],"contributors":json.loads(r[3]),"alerts":json.loads(r[4])} for r in reversed(rows)]


class OperationalValidationPlatform:
    """Observe-only operational assessment. It never changes trading decisions or config."""

    def __init__(self, *, paper_db: str = "data/dvs_paper_trades.db", signals_db: str = "data/dvs_signals.db", health_weights=None, regime_modifiers=None):
        self.paper_db = Path(paper_db)
        self.signals_db = Path(signals_db)
        self.coverage_engine = DataCoverageEngine()
        self.confidence_engine = ConfidenceDistributionEngine()
        self.regime_engine = RegimeValidationEngine()
        self.alert_center = OperationalAlertCenter()
        self.health_service = AIHealthService(str(self.paper_db), weights=health_weights, regime_modifiers=regime_modifiers)

    def _observation_rows(self) -> list[dict[str, Any]]:
        if not self.paper_db.exists():
            return []
        try:
            with sqlite3.connect(str(self.paper_db)) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(shadow_observations)")}
                if not columns:
                    return []
                selected = [name for name in ("id", "candidate_id", "symbol", "direction", "regime", "baseline_decision", "shadow_decision", "paper_trade_id", "outcome_r", "truth_json") if name in columns]
                rows = conn.execute(f"SELECT {','.join(selected)} FROM shadow_observations ORDER BY id").fetchall()
            return [dict(zip(selected, row)) for row in rows]
        except sqlite3.Error:
            return []

    def _confidence_values(self, limit: int = 5000) -> list[float]:
        if not self.signals_db.exists():
            return []
        try:
            with sqlite3.connect(str(self.signals_db)) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(scan_signals)")}
                if "confidence" not in columns:
                    return []
                return [float(row[0]) for row in conn.execute("SELECT confidence FROM scan_signals ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)).fetchall()]
        except (sqlite3.Error, TypeError, ValueError):
            return []

    def snapshot(self, *, calibration_state: str = "UNKNOWN", drift_state: str = "UNKNOWN",
                 reliability_state: str = "UNKNOWN", runtime_state: str = "UNKNOWN",
                 active_regime: str = "UNKNOWN", persist: bool = False) -> OperationalValidationSnapshot:
        rows = self._observation_rows()
        coverage = self.coverage_engine.evaluate(rows)
        confidence = self.confidence_engine.evaluate(self._confidence_values())
        regimes = self.regime_engine.evaluate(rows)
        alerts = self.alert_center.build(
            coverage=coverage, confidence=confidence, regimes=regimes,
            calibration_state=calibration_state, drift_state=drift_state,
            reliability_state=reliability_state, runtime_state=runtime_state,
        )
        health = self.health_service.evaluate(
            coverage=coverage, confidence=confidence, regimes=regimes, alerts=alerts,
            calibration_state=calibration_state, drift_state=drift_state,
            reliability_state=reliability_state, runtime_state=runtime_state,
            active_regime=active_regime,
        )
        if persist:
            self.health_service.append(health)
        return OperationalValidationSnapshot(health, coverage, confidence, regimes)
