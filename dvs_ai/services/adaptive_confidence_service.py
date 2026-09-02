from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from dvs_ai.services.probability_calibration_service import ProbabilityCalibrationService


@dataclass(frozen=True)
class AdaptiveConfidenceResult:
    state: str
    probability: float
    base_probability: float
    adjustment: float
    samples: int
    validation_samples: int
    reliability: float
    context_key: str
    reason: str = ""


class AdaptiveConfidenceService:
    """Observe-only contextual calibration for closed PAPER outcomes.

    It never changes CoinAnalysis.confidence_score, entry status, thresholds,
    position size, or execution behavior.
    """

    def __init__(
        self,
        db_path: str = "data/dvs_paper_trades.db",
        *,
        min_context_samples: int = 30,
        min_validation: int = 10,
        prior_strength: float = 24.0,
        max_adjustment: float = 8.0,
    ) -> None:
        self.db_path = Path(db_path)
        self.min_context_samples = max(20, int(min_context_samples))
        self.min_validation = max(8, int(min_validation))
        self.prior_strength = max(8.0, float(prior_strength))
        self.max_adjustment = min(12.0, max(2.0, float(max_adjustment)))
        self._rows: list[tuple[float, int, str, str]] = []

    @staticmethod
    def _finite(value: object, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if math.isfinite(number) else default

    @staticmethod
    def _clean_token(value: object, fallback: str) -> str:
        token = str(value or "").strip().upper()
        return token or fallback

    def fit(self) -> int:
        self._rows = []
        if not self.db_path.exists():
            return 0
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("""
                SELECT confidence, r_multiple, direction, regime
                FROM paper_trades
                WHERE status='CLOSED'
                  AND result NOT IN ('AMBIGUOUS','PARTIAL_AMBIGUOUS','EXPIRED')
                ORDER BY COALESCE(closed_at, created_at), id
            """).fetchall()
        for confidence, r_multiple, direction, regime in rows:
            c = self._finite(confidence, -1.0)
            r = self._finite(r_multiple, 0.0)
            if 0.0 <= c <= 100.0:
                self._rows.append((
                    c,
                    int(r > 0.0),
                    self._clean_token(direction, "UNKNOWN"),
                    self._clean_token(regime, "UNKNOWN"),
                ))
        return len(self._rows)

    @staticmethod
    def _brier(rows: list[tuple[float, int, str, str]], predictor) -> float:
        if not rows:
            return 0.0
        return sum((predictor(c) / 100.0 - y) ** 2 for c, y, _, _ in rows) / len(rows)

    def adapt(
        self,
        *,
        base_probability: float,
        raw_confidence: float,
        direction: str,
        regime: str,
        calibrator: ProbabilityCalibrationService,
    ) -> AdaptiveConfidenceResult:
        base = max(0.0, min(100.0, self._finite(base_probability)))
        if base <= 0.0:
            return AdaptiveConfidenceResult(
                "BASE_NOT_VALIDATED", 0.0, 0.0, 0.0, 0, 0, 0.0,
                "NONE", "global probability calibration is not validated",
            )
        if not self._rows:
            self.fit()
        d = self._clean_token(direction, "UNKNOWN")
        r = self._clean_token(regime, "UNKNOWN")
        context = [row for row in self._rows if row[2] == d and row[3] == r]
        key = f"{d}|{r}"
        if len(context) < self.min_context_samples:
            return AdaptiveConfidenceResult(
                "INSUFFICIENT_CONTEXT", base, base, 0.0, len(context), 0, 0.0,
                key, f"need at least {self.min_context_samples} context samples",
            )
        validation_count = max(self.min_validation, int(round(len(context) * 0.30)))
        validation_count = min(validation_count, len(context) - 15)
        if validation_count < self.min_validation:
            return AdaptiveConfidenceResult(
                "INSUFFICIENT_CONTEXT", base, base, 0.0, len(context),
                validation_count, 0.0, key, "not enough chronological holdout",
            )
        train = context[:-validation_count]
        validation = context[-validation_count:]
        wins = sum(y for _, y, _, _ in train)
        base_prior = base / 100.0
        posterior = (wins + self.prior_strength * base_prior) / (
            len(train) + self.prior_strength
        )
        target = posterior * 100.0
        reliability = len(train) / (len(train) + self.prior_strength)
        raw_adjustment = (target - base) * reliability
        adjustment = max(-self.max_adjustment, min(self.max_adjustment, raw_adjustment))
        candidate = max(0.0, min(100.0, base + adjustment))

        global_brier = self._brier(
            validation,
            lambda confidence: calibrator.calibrate(confidence)[0] or base,
        )
        candidate_brier = self._brier(validation, lambda _confidence: candidate)
        if candidate_brier > global_brier + 0.005:
            return AdaptiveConfidenceResult(
                "REJECTED_VALIDATION", base, base, 0.0, len(context),
                len(validation), reliability, key,
                "context adaptation did not pass chronological Brier holdout",
            )
        return AdaptiveConfidenceResult(
            "VALIDATED", candidate, base, adjustment, len(context),
            len(validation), reliability, key,
            "context adaptation passed chronological Brier holdout",
        )
