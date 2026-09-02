from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class CalibrationBin:
    low: float
    high: float
    samples: int
    wins: int
    raw_mean: float
    calibrated_probability: float


@dataclass(frozen=True)
class CalibrationModel:
    state: str
    samples: int
    train_samples: int
    validation_samples: int
    raw_brier: float
    calibrated_brier: float
    raw_ece: float
    calibrated_ece: float
    bins: tuple[CalibrationBin, ...]
    reason: str = ""

    @property
    def validated(self) -> bool:
        return self.state == "VALIDATED"


class ProbabilityCalibrationService:
    """Read-only PAPER calibration. Never changes trading gates or thresholds."""

    BIN_EDGES = (0.0, 50.0, 60.0, 70.0, 80.0, 90.0, 101.0)

    def __init__(
        self,
        db_path: str = "data/dvs_paper_trades.db",
        *,
        min_samples: int = 80,
        validation_ratio: float = 0.30,
        min_validation: int = 20,
    ) -> None:
        self.db_path = Path(db_path)
        self.min_samples = max(40, int(min_samples))
        self.validation_ratio = min(0.45, max(0.20, float(validation_ratio)))
        self.min_validation = max(10, int(min_validation))
        self._model: CalibrationModel | None = None

    @staticmethod
    def _finite(value: object, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if math.isfinite(number) else default

    def _load_rows(self) -> list[tuple[float, int]]:
        if not self.db_path.exists():
            return []
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("""
                SELECT confidence, r_multiple
                FROM paper_trades
                WHERE status='CLOSED'
                  AND result NOT IN ('AMBIGUOUS','PARTIAL_AMBIGUOUS','EXPIRED')
                ORDER BY COALESCE(closed_at, created_at), id
            """).fetchall()
        output: list[tuple[float, int]] = []
        for confidence, r_multiple in rows:
            c = self._finite(confidence, -1.0)
            r = self._finite(r_multiple, 0.0)
            if 0.0 <= c <= 100.0:
                output.append((c, int(r > 0.0)))
        return output

    @staticmethod
    def _pav(values: list[float], weights: list[int]) -> list[float]:
        blocks: list[list[float]] = []
        for index, (value, weight) in enumerate(zip(values, weights)):
            blocks.append([float(value), float(max(1, weight)), float(index), float(index)])
            while len(blocks) >= 2 and blocks[-2][0] > blocks[-1][0]:
                right = blocks.pop()
                left = blocks.pop()
                total = left[1] + right[1]
                merged = (left[0] * left[1] + right[0] * right[1]) / total
                blocks.append([merged, total, left[2], right[3]])
        result = [0.0] * len(values)
        for value, _, start, end in blocks:
            for idx in range(int(start), int(end) + 1):
                result[idx] = value
        return result

    def _fit_bins(self, rows: Iterable[tuple[float, int]]) -> tuple[CalibrationBin, ...]:
        rows = list(rows)
        global_wins = sum(outcome for _, outcome in rows)
        global_rate = global_wins / len(rows) if rows else 0.5
        raw_rates: list[float] = []
        weights: list[int] = []
        stats: list[tuple[float, float, int, int, float]] = []
        prior_strength = 6.0
        for low, high in zip(self.BIN_EDGES, self.BIN_EDGES[1:]):
            selected = [(c, y) for c, y in rows if low <= c < high]
            n = len(selected)
            wins = sum(y for _, y in selected)
            raw_mean = sum(c for c, _ in selected) / n if n else (low + min(high, 100.0)) / 2.0
            posterior = (wins + prior_strength * global_rate) / (n + prior_strength)
            raw_rates.append(posterior)
            weights.append(max(1, n))
            stats.append((low, high, n, wins, raw_mean))
        monotonic = self._pav(raw_rates, weights)
        return tuple(
            CalibrationBin(low, high, n, wins, raw_mean, max(0.0, min(100.0, p * 100.0)))
            for (low, high, n, wins, raw_mean), p in zip(stats, monotonic)
        )

    @staticmethod
    def _lookup(confidence: float, bins: tuple[CalibrationBin, ...]) -> float:
        for item in bins:
            if item.low <= confidence < item.high:
                return item.calibrated_probability
        return bins[-1].calibrated_probability if bins else confidence

    @staticmethod
    def _metrics(rows: list[tuple[float, int]], predictor) -> tuple[float, float]:
        if not rows:
            return 0.0, 0.0
        brier = sum((predictor(c) / 100.0 - y) ** 2 for c, y in rows) / len(rows)
        ece = 0.0
        edges = ProbabilityCalibrationService.BIN_EDGES
        for low, high in zip(edges, edges[1:]):
            group = [(c, y) for c, y in rows if low <= c < high]
            if not group:
                continue
            predicted = sum(predictor(c) for c, _ in group) / len(group) / 100.0
            observed = sum(y for _, y in group) / len(group)
            ece += len(group) / len(rows) * abs(predicted - observed)
        return brier, ece

    def fit(self, force: bool = False) -> CalibrationModel:
        if self._model is not None and not force:
            return self._model
        rows = self._load_rows()
        if len(rows) < self.min_samples:
            self._model = CalibrationModel(
                "INSUFFICIENT_DATA", len(rows), 0, 0, 0.0, 0.0, 0.0, 0.0, (),
                f"need at least {self.min_samples} determinate closed PAPER trades",
            )
            return self._model
        validation_count = max(self.min_validation, int(round(len(rows) * self.validation_ratio)))
        validation_count = min(validation_count, len(rows) - 30)
        train = rows[:-validation_count]
        validation = rows[-validation_count:]
        bins = self._fit_bins(train)
        raw_brier, raw_ece = self._metrics(validation, lambda c: c)
        calibrated_brier, calibrated_ece = self._metrics(
            validation, lambda c: self._lookup(c, bins)
        )
        non_worse = calibrated_brier <= raw_brier + 0.005
        ece_reasonable = calibrated_ece <= raw_ece + 0.02
        state = "VALIDATED" if non_worse and ece_reasonable else "REJECTED_VALIDATION"
        reason = "chronological holdout passed" if state == "VALIDATED" else "chronological holdout did not improve calibration safely"
        self._model = CalibrationModel(
            state, len(rows), len(train), len(validation), raw_brier,
            calibrated_brier, raw_ece, calibrated_ece, bins, reason,
        )
        return self._model

    def calibrate(self, confidence: float) -> tuple[float, CalibrationModel]:
        model = self.fit()
        raw = max(0.0, min(100.0, self._finite(confidence)))
        if not model.validated:
            return 0.0, model
        return self._lookup(raw, model.bins), model
