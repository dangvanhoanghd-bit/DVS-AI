from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .candidate_lifecycle_store import CandidateLifecycleStore
from .historical_candidate_store import HistoricalCandidateStore
from .historical_evidence_repository import HistoricalEvidenceRepository


@dataclass(frozen=True)
class CandidateComparison:
    state: str
    score: float
    reasons: tuple[str, ...]
    baseline: dict[str, float]
    candidate: dict[str, float]


class CandidateComparisonEngine:
    """Compare a candidate against the current SHADOW on the same holdout report."""

    def __init__(self, *, expectancy_epsilon: float = 0.02, drawdown_epsilon: float = 0.25,
                 brier_epsilon: float = 0.005, min_trades: int = 20) -> None:
        self.expectancy_epsilon = max(0.0, float(expectancy_epsilon))
        self.drawdown_epsilon = max(0.0, float(drawdown_epsilon))
        self.brier_epsilon = max(0.0, float(brier_epsilon))
        self.min_trades = max(1, int(min_trades))

    @staticmethod
    def _number(mapping: dict, key: str, default: float = 0.0) -> float:
        try:
            value = float(mapping.get(key, default))
            return value if math.isfinite(value) else default
        except (TypeError, ValueError):
            return default

    def compare(self, report: dict) -> CandidateComparison:
        if report.get("state") not in {"PASS", "REJECTED"}:
            return CandidateComparison("INSUFFICIENT_DATA", 0.0, ("backtest unavailable",), {}, {})
        baseline = dict(report.get("baseline", {}) or {})
        candidate = dict(report.get("candidate", {}) or {})
        n = int(self._number(candidate, "n"))
        if n < self.min_trades:
            return CandidateComparison("INSUFFICIENT_DATA", 0.0, (f"candidate trades {n} < {self.min_trades}",), baseline, candidate)
        exp_delta = self._number(candidate, "avg_r") - self._number(baseline, "avg_r")
        dd_delta = self._number(candidate, "max_dd") - self._number(baseline, "max_dd")
        brier_delta = self._number(candidate, "brier", 1.0) - self._number(baseline, "brier", 1.0)
        trade_ratio = n / max(1, int(self._number(baseline, "n", n)))
        reasons = (
            f"expectancy_delta={exp_delta:+.4f}",
            f"drawdown_delta={dd_delta:+.4f}",
            f"brier_delta={brier_delta:+.4f}",
            f"trade_ratio={trade_ratio:.3f}",
        )
        hard_worse = dd_delta > self.drawdown_epsilon or brier_delta > self.brier_epsilon or trade_ratio < 0.60
        better = exp_delta >= self.expectancy_epsilon and dd_delta <= self.drawdown_epsilon and brier_delta <= self.brier_epsilon
        if hard_worse or exp_delta < -self.expectancy_epsilon:
            state = "WORSE"
        elif better:
            state = "BETTER"
        else:
            state = "SIMILAR"
        score = 100.0 * exp_delta - 20.0 * max(0.0, dd_delta) - 100.0 * max(0.0, brier_delta)
        return CandidateComparison(state, round(score, 4), reasons, baseline, candidate)


class CandidateEvidenceRepository:
    """Read-only discovery of candidate/backtest/promotion artifacts for the dashboard."""

    def __init__(self, data_dir: str = "data", promotion_dir: str = "data/shadow_promotions") -> None:
        self.data_dir = Path(data_dir)
        self.promotion_dir = Path(promotion_dir)
        self.comparison = CandidateComparisonEngine()
        self.lifecycle = CandidateLifecycleStore(str(self.data_dir / "dvs_paper_trades.db"))
        self.performance = HistoricalCandidateStore(str(self.data_dir / "dvs_paper_trades.db"))
        self.historical = HistoricalEvidenceRepository(str(self.data_dir / "dvs_paper_trades.db"), str(self.promotion_dir))

    @staticmethod
    def _read(path: Path) -> dict:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def list_candidates(self) -> list[dict[str, Any]]:
        candidate_path = self.data_dir / "quantum_shadow_candidate.json"
        backtest_path = self.data_dir / "quantum_shadow_backtest.json"
        rows: list[dict[str, Any]] = []
        if candidate_path.exists():
            candidate = self._read(candidate_path)
            backtest = self._read(backtest_path) if backtest_path.exists() else {}
            comparison = self.comparison.compare(backtest)
            rows.append({
                "candidate_id": candidate.get("candidate_id") or candidate_path.stem,
                "created_at": candidate.get("generated_at", ""),
                "candidate_path": str(candidate_path),
                "backtest_state": backtest.get("state", "PENDING"),
                "comparison_state": comparison.state,
                "comparison_score": comparison.score,
                "promotion_state": "PENDING",
                "details": comparison.reasons,
            })
        if self.promotion_dir.exists():
            for path in sorted(self.promotion_dir.glob("promotion_*.json"), reverse=True):
                audit = self._read(path)
                rows.append({
                    "candidate_id": audit.get("candidate_schema") or path.stem,
                    "created_at": audit.get("applied_at", ""),
                    "candidate_path": "",
                    "backtest_state": audit.get("backtest_state", "UNKNOWN"),
                    "comparison_state": "APPLIED",
                    "comparison_score": 0.0,
                    "promotion_state": "APPLIED",
                    "details": (f"audit={path.name}",),
                })
        return rows

    def timeline(self) -> list[dict[str, Any]]:
        events=[]
        for event in self.lifecycle.events():
            events.append({"time": event.occurred_at, "candidate_id": event.candidate_id, "state": event.new_state, "reason": event.reason})
        if not events:
            for row in self.list_candidates():
                events.append({"time": row.get("created_at", ""), "candidate_id": row["candidate_id"], "state": row["promotion_state"]})
        return sorted(events, key=lambda x: str(x.get("time", "")))

    def historical_candidates(self) -> list[dict[str, Any]]:
        return self.historical.comparison()

    def candidate_dossier(self, candidate_id: str) -> dict[str, Any]:
        return self.historical.dossier(candidate_id)

    def historical_integrity(self) -> dict[str, Any]:
        return asdict(self.historical.audit_integrity())

    def candidate_trend(self, candidate_id: str) -> list[dict[str, Any]]:
        return [vars(x) for x in self.performance.snapshots(candidate_id)]
