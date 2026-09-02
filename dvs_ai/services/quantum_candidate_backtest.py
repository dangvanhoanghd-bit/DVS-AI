from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .quantum_optimizer import OptimizationParams, QuantumOptimizer


class CandidateBacktestService:
    """Truth-qualified chronological simulation for a Quantum SHADOW candidate.

    This service is evaluation-only. It never writes config and never imports
    execution/order-routing code.
    """

    FORBIDDEN_PREFIXES = ("main_",)

    def __init__(
        self,
        optimizer: QuantumOptimizer,
        *,
        fee_r: float = 0.02,
        slippage_r: float = 0.015,
        min_selected: int = 20,
        max_drawdown_increase: float = 1.0,
        min_expectancy_delta: float = 0.0,
        max_brier_degradation: float = 0.01,
    ) -> None:
        self.optimizer = optimizer
        self.fee_r = max(0.0, float(fee_r))
        self.slippage_r = max(0.0, float(slippage_r))
        self.min_selected = max(12, int(min_selected))
        self.max_drawdown_increase = max(0.0, float(max_drawdown_increase))
        self.min_expectancy_delta = float(min_expectancy_delta)
        self.max_brier_degradation = max(0.0, float(max_brier_degradation))

    @staticmethod
    def _brier(rows: list[Any]) -> float:
        if not rows:
            return 1.0
        values = []
        for row in rows:
            probability = min(1.0, max(0.0, float(row.confidence) / 100.0))
            outcome = 1.0 if float(row.r_multiple) > 0 else 0.0
            values.append((probability - outcome) ** 2)
        return sum(values) / len(values)

    def _params_from_candidate(self, payload: dict, base: OptimizationParams) -> OptimizationParams:
        candidate = dict(payload.get("candidate", {}) or {})
        forbidden = sorted(k for k in candidate if str(k).startswith(self.FORBIDDEN_PREFIXES))
        if forbidden:
            raise ValueError(f"Candidate chứa MAIN keys bị cấm: {forbidden}")
        data = asdict(base)
        for key in ("shadow_confidence", "shadow_entry", "shadow_risk_max", "shadow_rr_min"):
            if key in candidate:
                data[key] = float(candidate[key])
        weights = dict(payload.get("evidence_fusion_family_weights", {}) or {})
        mapping = {
            "TIMING": "weight_timing", "ENTRY": "weight_entry",
            "ORDER_FLOW": "weight_order_flow", "DIRECTION": "weight_direction",
            "MARKET": "weight_market",
        }
        for family, field in mapping.items():
            if family in weights:
                data[field] = float(weights[family])
        return OptimizationParams(**data).clamp()

    def _net_rows(self, rows: list[Any]) -> list[Any]:
        cost = self.fee_r + self.slippage_r
        return [
            row.__class__(**{**row.__dict__, "r_multiple": float(row.r_multiple) - cost})
            for row in rows
        ]

    def simulate(self, candidate_payload: dict) -> dict:
        if not bool(candidate_payload.get("human_approval_required", False)):
            raise ValueError("Candidate thiếu human approval guardrail.")
        if candidate_payload.get("main_config_mutated") is not False:
            raise ValueError("Candidate không chứng minh MAIN immutable.")
        rows = self.optimizer._load_closed()
        if len(rows) < self.optimizer.min_closed:
            return {
                "schema": "DVS_SHADOW_BACKTEST_V1",
                "state": "INSUFFICIENT_QUALITY_DATA",
                "eligible_samples": len(rows),
                "required": self.optimizer.min_closed,
                "approved_for_human_review": False,
                "training_audit": dict(self.optimizer._last_training_audit),
            }
        _, holdout = self.optimizer._chronological_split(rows, self.optimizer.validation_ratio)
        base = self.optimizer._base_params()
        proposed = self._params_from_candidate(candidate_payload, base)
        baseline_selected = [r for r in holdout if self.optimizer._passes(r, base, "SHADOW")]
        proposed_selected = [r for r in holdout if self.optimizer._passes(r, proposed, "SHADOW")]
        baseline_net = self._net_rows(baseline_selected)
        proposed_net = self._net_rows(proposed_selected)
        baseline_stats = self.optimizer._stats(baseline_net)
        proposed_stats = self.optimizer._stats(proposed_net)
        baseline_brier = self._brier(baseline_selected)
        proposed_brier = self._brier(proposed_selected)
        checks = {
            "minimum_trades": proposed_stats["n"] >= self.min_selected,
            "expectancy_not_worse": proposed_stats["avg_r"] >= baseline_stats["avg_r"] + self.min_expectancy_delta,
            "drawdown_guardrail": proposed_stats["max_dd"] <= baseline_stats["max_dd"] + self.max_drawdown_increase,
            "calibration_guardrail": proposed_brier <= baseline_brier + self.max_brier_degradation,
            "truth_qualified_only": len(rows) == int(self.optimizer._last_training_audit.get("eligible", len(rows))),
        }
        approved = all(checks.values())
        return {
            "schema": "DVS_SHADOW_BACKTEST_V1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "state": "PASS" if approved else "REJECTED",
            "approved_for_human_review": approved,
            "candidate_schema": candidate_payload.get("schema"),
            "candidate_path": candidate_payload.get("path", ""),
            "holdout_samples": len(holdout),
            "fee_r": self.fee_r,
            "slippage_r": self.slippage_r,
            "baseline": {**baseline_stats, "brier": baseline_brier},
            "candidate": {**proposed_stats, "brier": proposed_brier},
            "checks": checks,
            "training_audit": dict(self.optimizer._last_training_audit),
            "limitations": [
                "PAPER truth-qualified chronological holdout only.",
                "No counterfactual outcome exists for trades filtered out by both configurations.",
                "Simulation does not authorize MAIN or LIVE execution.",
            ],
        }

    @staticmethod
    def save_report(report: dict, path: str = "data/quantum_shadow_backtest.json") -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return target
