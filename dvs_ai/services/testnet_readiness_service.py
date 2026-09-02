from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else float(default)
    except (TypeError, ValueError):
        return float(default)


@dataclass(frozen=True)
class ReadinessRuleResult:
    code: str
    dimension: str
    state: str
    score: float
    reason: str
    recommendation: str
    blocking: bool = False


@dataclass(frozen=True)
class TestnetReadinessSnapshot:
    score: float
    state: str
    rules: tuple[ReadinessRuleResult, ...]
    generated_at: str
    recommendation: str
    missing_requirements: tuple[str, ...]
    testnet_enabled: bool = False
    live_enabled: bool = False


class TestnetReadinessAuditService:
    __test__ = False
    """Observe-only audit. It never enables Testnet, LIVE, or execution."""

    DIMENSION_WEIGHTS = {
        "DATA": 25.0,
        "OPERATIONAL": 25.0,
        "STATISTICAL": 20.0,
        "INTEGRITY": 15.0,
        "SAFETY": 15.0,
    }

    def __init__(self, db_path: str = "data/dvs_paper_trades.db"):
        self.db_path = Path(db_path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS testnet_readiness_history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generated_at TEXT NOT NULL,
                score REAL NOT NULL,
                state TEXT NOT NULL,
                rules_json TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                missing_json TEXT NOT NULL,
                snapshot_key TEXT NOT NULL UNIQUE
                )"""
            )

    @staticmethod
    def _rule(code: str, dimension: str, state: str, score: float, reason: str,
              recommendation: str, blocking: bool = False) -> ReadinessRuleResult:
        return ReadinessRuleResult(code, dimension, state, max(0.0, min(1.0, _finite(score))), reason, recommendation, bool(blocking))

    def evaluate(self, *, operational: Any = None, historical_integrity: Mapping[str, Any] | None = None,
                 candidate_state: str = "NONE", candidate_readiness: str = "NOT_EVALUATED",
                 main_immutable: bool = True, live_enabled: bool = False,
                 testnet_enabled: bool = False) -> TestnetReadinessSnapshot:
        health = getattr(operational, "health", None)
        coverage = getattr(operational, "coverage", None)
        regimes = getattr(operational, "regimes", None)
        rules: list[ReadinessRuleResult] = []

        coverage_state = str(getattr(coverage, "state", "BLOCKED")).upper()
        eligible = int(getattr(coverage, "eligible", 0) or 0)
        data_score = {"FULL": 1.0, "DEGRADED": 0.55, "BLOCKED": 0.0}.get(coverage_state, 0.0)
        rules.append(self._rule(
            "DATA_COVERAGE", "DATA", "PASS" if coverage_state == "FULL" else "WATCH" if coverage_state == "DEGRADED" else "FAIL",
            data_score, f"Coverage {coverage_state}; eligible observations {eligible}.",
            "Tiếp tục Auto PAPER và tăng độ phủ Bull/Bear/Range, LONG/SHORT." if coverage_state != "FULL" else "Duy trì thu thập PAPER để bảo toàn coverage.",
            coverage_state == "BLOCKED",
        ))

        health_state = str(getattr(health, "state", "CRITICAL")).upper()
        health_score = _finite(getattr(health, "score", 0.0)) / 100.0
        operational_fail = health_state == "CRITICAL" or any(getattr(a, "severity", "") == "CRITICAL" for a in (getattr(health, "alerts", ()) or ()))
        rules.append(self._rule(
            "OPERATIONAL_HEALTH", "OPERATIONAL", "FAIL" if operational_fail else "PASS" if health_state in {"HEALTHY", "STABLE"} else "WATCH",
            health_score, f"AI Health {health_state} ({health_score*100:.1f}/100).",
            "Khắc phục Critical alerts trước mọi review Testnet." if operational_fail else "Tiếp tục quan sát Operational Validation.",
            operational_fail,
        ))

        regime_state = str(getattr(regimes, "state", "INSUFFICIENT_DATA")).upper()
        candidate_ready = str(candidate_readiness or "NOT_EVALUATED").upper() in {"READY_FOR_REVIEW", "READY_FOR_NEXT_REVIEW", "SUPPORTED"}
        statistical_score = 1.0 if regime_state == "SUPPORTED" and candidate_ready else 0.55 if regime_state in {"CONTINUE_OBSERVATION", "SUPPORTED"} else 0.0
        rules.append(self._rule(
            "STATISTICAL_EVIDENCE", "STATISTICAL", "PASS" if statistical_score == 1.0 else "WATCH" if statistical_score > 0 else "FAIL",
            statistical_score,
            f"Regime validation {regime_state}; Candidate readiness {candidate_readiness}; lifecycle {candidate_state}.",
            "Tiếp tục observation cho tới khi Candidate và regime evidence cùng READY." if statistical_score < 1 else "Đủ bằng chứng để human review; chưa cấp quyền Testnet.",
            statistical_score == 0.0,
        ))

        integrity = dict(historical_integrity or {})
        integrity_state = str(integrity.get("state", "UNKNOWN")).upper()
        integrity_score = 1.0 if integrity_state == "PASS" else 0.45 if integrity_state in {"UNKNOWN", "INSUFFICIENT_DATA"} else 0.0
        rules.append(self._rule(
            "EVIDENCE_INTEGRITY", "INTEGRITY", "PASS" if integrity_score == 1 else "WATCH" if integrity_score > 0 else "FAIL",
            integrity_score, f"Historical evidence integrity: {integrity_state}.",
            "Chạy integrity audit và xử lý mọi orphan/sequence issue." if integrity_score < 1 else "Integrity chain hợp lệ.",
            integrity_score == 0.0,
        ))

        safety_ok = bool(main_immutable) and not bool(live_enabled) and not bool(testnet_enabled)
        rules.append(self._rule(
            "SAFETY_LOCKS", "SAFETY", "PASS" if safety_ok else "FAIL", 1.0 if safety_ok else 0.0,
            f"MAIN immutable={bool(main_immutable)}; Testnet enabled={bool(testnet_enabled)}; LIVE enabled={bool(live_enabled)}.",
            "Giữ Testnet/LIVE khóa và MAIN immutable." if safety_ok else "Khóa ngay Testnet/LIVE và phục hồi MAIN immutability.",
            not safety_ok,
        ))

        by_dimension: dict[str, list[float]] = {}
        for rule in rules:
            by_dimension.setdefault(rule.dimension, []).append(rule.score)
        total = 0.0
        for dimension, weight in self.DIMENSION_WEIGHTS.items():
            values = by_dimension.get(dimension, [0.0])
            total += weight * (sum(values) / len(values))
        score = max(0.0, min(100.0, total))
        blockers = [r for r in rules if r.blocking or r.state == "FAIL"]
        missing = tuple(r.reason for r in rules if r.state != "PASS")
        if not safety_ok:
            state = "NOT_READY"
        elif any(r.code == "OPERATIONAL_HEALTH" and r.state == "FAIL" for r in rules):
            state = "OPERATIONAL_RISK"
        elif any(r.code in {"DATA_COVERAGE", "STATISTICAL_EVIDENCE"} and r.state == "FAIL" for r in rules):
            state = "DATA_INSUFFICIENT"
        elif blockers or score < 85:
            state = "CONTINUE_PAPER"
        else:
            state = "READY_FOR_MANUAL_TESTNET_REVIEW"
        recommendation = {
            "NOT_READY": "Khôi phục safety locks trước mọi bước tiếp theo.",
            "OPERATIONAL_RISK": "Khắc phục Operational Critical alerts và tiếp tục PAPER.",
            "DATA_INSUFFICIENT": "Tiếp tục PAPER để bổ sung dữ liệu và statistical evidence.",
            "CONTINUE_PAPER": "Duy trì PAPER; xử lý các mục WATCH trước human review.",
            "READY_FOR_MANUAL_TESTNET_REVIEW": "Có thể mở vòng human review riêng; Testnet vẫn chưa được bật.",
        }[state]
        return TestnetReadinessSnapshot(round(score, 2), state, tuple(rules), datetime.now(timezone.utc).isoformat(), recommendation, missing, False, False)

    def append(self, snapshot: TestnetReadinessSnapshot, snapshot_key: str | None = None) -> bool:
        key = snapshot_key or f"{snapshot.generated_at[:16]}:{snapshot.state}:{snapshot.score:.1f}"
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    "INSERT INTO testnet_readiness_history(generated_at,score,state,rules_json,recommendation,missing_json,snapshot_key) VALUES(?,?,?,?,?,?,?)",
                    (snapshot.generated_at, snapshot.score, snapshot.state, json.dumps([asdict(x) for x in snapshot.rules], sort_keys=True), snapshot.recommendation, json.dumps(snapshot.missing_requirements), key),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute("SELECT generated_at,score,state,rules_json,recommendation,missing_json FROM testnet_readiness_history ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)).fetchall()
        return [{"generated_at": r[0], "score": r[1], "state": r[2], "rules": json.loads(r[3]), "recommendation": r[4], "missing": json.loads(r[5])} for r in reversed(rows)]
