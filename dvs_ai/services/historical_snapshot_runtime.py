from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .candidate_lifecycle_store import CandidateLifecycleStore
from .historical_candidate_store import HistoricalCandidateStore
from .historical_readiness_trend import HistoricalReadinessTrendAudit, HistoricalReadinessTrendStore
from .shadow_observation_service import ObservationQualityAudit, ShadowObservationStore


@dataclass(frozen=True)
class SnapshotRuntimeResult:
    state: str
    candidate_id: str
    eligible: int
    snapshot_id: int | None
    snapshot_key: str
    reason: str


class HistoricalSnapshotRuntime:
    """Creates deterministic, append-only performance snapshots from eligible observations."""

    def __init__(self, *, observation_store: ShadowObservationStore,
                 performance_store: HistoricalCandidateStore | None = None,
                 lifecycle_store: CandidateLifecycleStore | None = None,
                 quality_audit: ObservationQualityAudit | None = None,
                 window_size: int = 20, readiness_audit: HistoricalReadinessTrendAudit | None = None,
                 readiness_store: HistoricalReadinessTrendStore | None = None) -> None:
        self.observation_store = observation_store
        db_path = str(observation_store.db_path)
        self.performance_store = performance_store or HistoricalCandidateStore(db_path)
        self.lifecycle_store = lifecycle_store or CandidateLifecycleStore(db_path)
        self.quality_audit = quality_audit or ObservationQualityAudit(min_eligible=max(1, int(window_size)))
        self.window_size = max(1, int(window_size))
        self.readiness_audit = readiness_audit or HistoricalReadinessTrendAudit()
        self.readiness_store = readiness_store or HistoricalReadinessTrendStore(db_path)
        self.stats = {"attempted": 0, "created": 0, "deduplicated": 0, "blocked": 0, "errors": 0, "readiness_ready": 0}
        self.last_readiness = None

    @staticmethod
    def _selected(value: Any) -> bool:
        return str(value or "").upper() in {"READY", "SETUP", "OPEN", "TRUE", "1"}

    @staticmethod
    def _finite(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
            return number if math.isfinite(number) else default
        except (TypeError, ValueError):
            return default

    @classmethod
    def _series(cls, rows: list[dict[str, Any]], key: str) -> list[float]:
        return [cls._finite(row.get("outcome_r")) if cls._selected(row.get(key)) else 0.0 for row in rows]

    @staticmethod
    def _max_drawdown(values: list[float]) -> float:
        equity = peak = 0.0
        max_dd = 0.0
        for value in values:
            equity += value
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        return max_dd

    @staticmethod
    def _profit_factor(values: list[float]) -> float:
        gains = sum(v for v in values if v > 0)
        losses = -sum(v for v in values if v < 0)
        if losses <= 1e-12:
            return gains if gains > 0 else 0.0
        return gains / losses

    @classmethod
    def _brier_ece(cls, rows: list[dict[str, Any]]) -> tuple[float, float]:
        pairs: list[tuple[float, float]] = []
        for row in rows:
            try:
                truth = json.loads(row.get("truth_json") or "{}")
            except Exception:
                truth = {}
            probability = cls._finite(truth.get("adaptive_probability", truth.get("calibrated_probability", truth.get("confidence", 0.0))))
            if probability > 1.0:
                probability /= 100.0
            probability = min(1.0, max(0.0, probability))
            outcome = 1.0 if cls._finite(row.get("outcome_r")) > 0 else 0.0
            pairs.append((probability, outcome))
        if not pairs:
            return 0.0, 0.0
        brier = sum((p-y) ** 2 for p, y in pairs) / len(pairs)
        bins: dict[int, list[tuple[float, float]]] = {}
        for p, y in pairs:
            bins.setdefault(min(9, int(p * 10)), []).append((p, y))
        ece = sum(len(items) / len(pairs) * abs(sum(p for p, _ in items)/len(items) - sum(y for _, y in items)/len(items)) for items in bins.values())
        return brier, ece

    @classmethod
    def _reliability_and_drift(cls, rows: list[dict[str, Any]]) -> tuple[float, str]:
        reliabilities: list[float] = []
        states: list[str] = []
        for row in rows:
            try:
                truth = json.loads(row.get("truth_json") or "{}")
            except Exception:
                truth = {}
            value = truth.get("evidence_reliability")
            if value is not None:
                reliabilities.append(min(1.0, max(0.0, cls._finite(value))))
            states.append(str(truth.get("drift_state") or "INSUFFICIENT_DATA").upper())
        priority = {"DRIFT": 3, "WATCH": 2, "STABLE": 1, "INSUFFICIENT_DATA": 0}
        drift = max(states, key=lambda state: priority.get(state, 0)) if states else "INSUFFICIENT_DATA"
        return (sum(reliabilities)/len(reliabilities) if reliabilities else 0.0), drift

    def capture(self, candidate_id: str, *, force: bool = False, captured_at: str | None = None) -> SnapshotRuntimeResult:
        self.stats["attempted"] += 1
        cid = str(candidate_id).strip()
        try:
            quality = self.quality_audit.evaluate(self.observation_store.all_rows(cid))
            eligible = len(quality.eligible_rows)
            if quality.state == "BLOCKED" or eligible < self.window_size:
                self.stats["blocked"] += 1
                return SnapshotRuntimeResult("BLOCKED", cid, eligible, None, "", "; ".join(quality.reasons))
            boundary = eligible if force else (eligible // self.window_size) * self.window_size
            if boundary < self.window_size:
                self.stats["blocked"] += 1
                return SnapshotRuntimeResult("BLOCKED", cid, eligible, None, "", "window not complete")
            rows = list(quality.eligible_rows)[-boundary:]
            key = f"{cid}:eligible:{boundary}:window:{self.window_size}"
            shadow = self._series(rows, "shadow_decision")
            observations = len(rows)
            expectancy = sum(shadow) / observations if observations else 0.0
            win_rate = sum(1 for value in shadow if value > 0) / observations if observations else 0.0
            brier, ece = self._brier_ece(rows)
            reliability, drift = self._reliability_and_drift(rows)
            coverage_counts: dict[str, int] = {}
            regime_metrics: dict[str, dict[str, float]] = {}
            for row, value in zip(rows, shadow):
                regime = str(row.get("regime") or "UNKNOWN").upper()
                coverage_counts[regime] = coverage_counts.get(regime, 0) + 1
                bucket = regime_metrics.setdefault(regime, {"count": 0.0, "sum_r": 0.0, "wins": 0.0})
                bucket["count"] += 1; bucket["sum_r"] += value; bucket["wins"] += 1 if value > 0 else 0
            for bucket in regime_metrics.values():
                count = max(1.0, bucket["count"])
                bucket["expectancy"] = bucket["sum_r"] / count
                bucket["win_rate"] = bucket["wins"] / count
            coverage = min(1.0, len([v for v in coverage_counts.values() if v >= 3]) / 4.0)
            snapshot_id = self.performance_store.append_once(
                cid, snapshot_key=key, observations=observations, expectancy=expectancy,
                max_drawdown=self._max_drawdown(shadow), win_rate=win_rate,
                profit_factor=self._profit_factor(shadow), brier=brier, ece=ece,
                reliability=reliability, drift_state=drift, coverage=coverage,
                regime_metrics=regime_metrics, captured_at=captured_at or datetime.now(timezone.utc).isoformat(),
            )
            if snapshot_id is None:
                self.stats["deduplicated"] += 1
                return SnapshotRuntimeResult("DEDUPLICATED", cid, eligible, None, key, "snapshot already exists")
            self.stats["created"] += 1
            state = self.lifecycle_store.current_state(cid)
            if state == "APPLIED_TO_SHADOW":
                self.lifecycle_store.transition(cid, "OBSERVING", reason="first historical snapshot captured", actor="SNAPSHOT_RUNTIME", metadata={"snapshot_id": snapshot_id})
            readiness = self.readiness_audit.evaluate(cid, self.performance_store.snapshots(cid, limit=10000))
            self.last_readiness = readiness
            self.readiness_store.append_once(readiness)
            current = self.lifecycle_store.current_state(cid)
            if readiness.state == "READY_FOR_REVIEW" and current == "OBSERVING":
                self.lifecycle_store.transition(cid, "READY_FOR_REVIEW", reason="historical readiness stable across snapshot windows", actor="READINESS_TREND_AUDIT", metadata={"snapshot_id": snapshot_id, "metrics": readiness.metrics})
                self.stats["readiness_ready"] += 1
            return SnapshotRuntimeResult("CREATED", cid, eligible, snapshot_id, key, readiness.state)
        except Exception as exc:
            self.stats["errors"] += 1
            return SnapshotRuntimeResult("ERROR", cid, 0, None, "", str(exc))

    def diagnostics(self) -> dict[str, Any]:
        readiness=self.last_readiness
        return {**self.stats, "window_size": self.window_size,
                "readiness_state": getattr(readiness,"state","NOT_EVALUATED"),
                "readiness_snapshots": getattr(readiness,"snapshots",0)}
