from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .quantum_data_convergence import QuantumDataAdapter
from .unified_outcome_service import UnifiedOutcomeService
from .legacy_path_telemetry import emit_legacy_sql_path_used


@dataclass(frozen=True)
class ReadinessMetric:
    key: str
    label: str
    current: int
    required: int
    state: str

    @property
    def missing(self) -> int:
        return max(0, int(self.required) - int(self.current))

    @property
    def percent(self) -> int:
        if self.required <= 0:
            return 100
        return max(0, min(100, round(100 * self.current / self.required)))


@dataclass(frozen=True)
class QuantumReadinessSnapshot:
    state: str
    eligible: int
    required: int
    total_closed: int
    metrics: tuple[ReadinessMetric, ...]
    calibration_state: str
    reliability_state: str
    velocity_per_day: float | None
    eta_days: float | None
    eta_reliable: bool
    audit: dict[str, int]
    generated_at: str

    @property
    def missing(self) -> int:
        return max(0, self.required - self.eligible)


class QuantumReadinessService:
    """Observe-only readiness diagnostics for Quantum training.

    The eligibility rules intentionally mirror QuantumOptimizer._load_closed():
    CLOSED + determinate outcome + valid DVS_QUANTUM_TRAINING_V1 snapshot +
    calibration VALIDATED + drift STABLE + order-flow FULL.
    """

    DEFAULT_REQUIRED = 80
    COVERAGE_TARGET = 30
    REGIME_KEYS = ("TREND", "RANGE", "ACCUMULATION", "DISTRIBUTION", "VOLATILE")

    def __init__(
        self, db_path: str | Path, required: int = DEFAULT_REQUIRED,
        outcome_adapter: QuantumDataAdapter | None = None,
        unified_service: UnifiedOutcomeService | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.required = max(1, int(required))
        self.outcome_adapter = outcome_adapter
        self.unified_service = unified_service or UnifiedOutcomeService(self.db_path)

    @staticmethod
    def _valid_snapshot(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        for family in ("TIMING", "ENTRY", "ORDER_FLOW", "DIRECTION", "MARKET"):
            item = payload.get(family)
            if not isinstance(item, dict) or not bool(item.get("available", False)):
                return False
            try:
                score = float(item.get("score"))
                quality = float(item.get("quality"))
            except (TypeError, ValueError):
                return False
            if not math.isfinite(score) or not math.isfinite(quality) or not 0.0 <= quality <= 1.0:
                return False
        truth = payload.get("_TRUTH")
        return isinstance(truth, dict) and truth.get("schema") == "DVS_QUANTUM_TRAINING_V1"

    @staticmethod
    def _parse_time(value: str) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def snapshot(self) -> QuantumReadinessSnapshot:
        audit = {
            "total_closed": 0,
            "eligible": 0,
            "excluded_missing_snapshot": 0,
            "excluded_invalid_snapshot": 0,
            "excluded_calibration": 0,
            "excluded_drift": 0,
            "excluded_order_flow_quality": 0,
        }
        counts = {"LONG": 0, "SHORT": 0, **{key: 0 for key in self.REGIME_KEYS}}
        eligible_times: list[datetime] = []
        calibration_states: list[str] = []
        reliability_states: list[str] = []

        if self.outcome_adapter is not None:
            emit_legacy_sql_path_used(__name__, "QuantumReadinessService.snapshot", "INJECTED_RAW_ADAPTER")
            try:
                terminal_rows = self.outcome_adapter.read_terminal()
            except (FileNotFoundError, ValueError):
                terminal_rows = []
            rows = [row for row in terminal_rows if row.outcome in ("WIN", "LOSS")]
        else:
            try:
                rows = self.unified_service.learning_ready()
                if not rows and not self.unified_service.pipeline_schema_available():
                    rows = self.unified_service.legacy_compat_learning_ready()
            except (FileNotFoundError, ValueError):
                rows = []
        audit["total_closed"] = len(rows)
        for row in rows:
            snapshot = row.evidence_snapshot
            if snapshot is None:
                if bool(row.provenance.get("evidence_snapshot_present", False)):
                    audit["excluded_invalid_snapshot"] += 1
                else:
                    audit["excluded_missing_snapshot"] += 1
                continue
            if not self._valid_snapshot(snapshot):
                audit["excluded_invalid_snapshot"] += 1
                continue
            truth = snapshot["_TRUTH"]
            calibration = str(truth.get("calibration_state", "UNKNOWN")).upper()
            drift = str(truth.get("drift_state", "UNKNOWN")).upper()
            order_flow = str(truth.get("order_flow_quality", "UNKNOWN")).upper()
            calibration_states.append(calibration)
            reliability_states.append(str(
                truth.get("reliability_state", truth.get("evidence_reliability_state", "UNKNOWN"))
            ).upper())
            if calibration != "VALIDATED":
                audit["excluded_calibration"] += 1
                continue
            if drift != "STABLE":
                audit["excluded_drift"] += 1
                continue
            if order_flow != "FULL":
                audit["excluded_order_flow_quality"] += 1
                continue
            audit["eligible"] += 1
            d = str(row.direction or "").upper()
            r = str(row.regime or "").upper()
            if d in ("LONG", "SHORT"):
                counts[d] += 1
            if r in counts:
                counts[r] += 1
            parsed = self._parse_time(str(row.setup_time))
            if parsed is not None:
                eligible_times.append(parsed)

        eligible = audit["eligible"]
        metrics = [
            ReadinessMetric("eligible", "FULL · VALIDATED · STABLE", eligible, self.required,
                            "READY" if eligible >= self.required else "COLLECTING"),
            ReadinessMetric("long", "LONG đủ chuẩn", counts["LONG"], self.COVERAGE_TARGET,
                            "COVERED" if counts["LONG"] >= self.COVERAGE_TARGET else "LOW"),
            ReadinessMetric("short", "SHORT đủ chuẩn", counts["SHORT"], self.COVERAGE_TARGET,
                            "COVERED" if counts["SHORT"] >= self.COVERAGE_TARGET else "LOW"),
        ]
        for key in self.REGIME_KEYS:
            metrics.append(ReadinessMetric(key.lower(), f"Regime {key}", counts[key], self.COVERAGE_TARGET,
                                           "COVERED" if counts[key] >= self.COVERAGE_TARGET else "LOW"))

        velocity = None
        eta = None
        eta_reliable = False
        if len(eligible_times) >= 10:
            span_days = (max(eligible_times) - min(eligible_times)).total_seconds() / 86400.0
            if span_days >= 1.0:
                velocity = len(eligible_times) / span_days
                if velocity > 0 and eligible < self.required:
                    eta = (self.required - eligible) / velocity
                eta_reliable = True

        calibration_state = "VALIDATED" if calibration_states and all(x == "VALIDATED" for x in calibration_states[-20:]) else (
            calibration_states[-1] if calibration_states else "UNKNOWN"
        )
        known_rel = [x for x in reliability_states if x and x != "UNKNOWN"]
        reliability_state = known_rel[-1] if known_rel else "UNKNOWN"
        state = "READY" if eligible >= self.required else "INSUFFICIENT_QUALITY_DATA"
        return QuantumReadinessSnapshot(
            state=state,
            eligible=eligible,
            required=self.required,
            total_closed=audit["total_closed"],
            metrics=tuple(metrics),
            calibration_state=calibration_state,
            reliability_state=reliability_state,
            velocity_per_day=velocity,
            eta_days=eta,
            eta_reliable=eta_reliable,
            audit=dict(audit),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
