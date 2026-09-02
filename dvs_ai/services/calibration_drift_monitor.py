from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from dvs_ai.services.probability_calibration_service import ProbabilityCalibrationService
from dvs_ai.services.truth_trend_store import TruthTrendStore


@dataclass(frozen=True)
class CalibrationDriftReport:
    state: str
    samples: int
    reference_samples: int
    recent_samples: int
    reference_brier: float
    recent_brier: float
    reference_ece: float
    recent_ece: float
    confidence_psi: float
    reasons: tuple[str, ...] = ()

    @property
    def drifted(self) -> bool:
        return self.state == "DRIFT"


class CalibrationDriftMonitor:
    """Observe-only drift monitor for CLOSED PAPER outcomes.

    It performs a chronological reference/recent comparison. It never changes
    thresholds, confidence_score, position sizing, paper eligibility, or
    execution behavior.
    """

    def __init__(
        self,
        db_path: str = "data/dvs_paper_trades.db",
        *,
        min_samples: int = 120,
        recent_window: int = 40,
        drift_brier_delta: float = 0.04,
        watch_brier_delta: float = 0.02,
        drift_ece_delta: float = 0.08,
        watch_ece_delta: float = 0.04,
        drift_psi: float = 0.25,
        watch_psi: float = 0.10,
    ) -> None:
        self.db_path = Path(db_path)
        self.min_samples = max(80, int(min_samples))
        self.recent_window = max(20, int(recent_window))
        self.drift_brier_delta = max(0.01, float(drift_brier_delta))
        self.watch_brier_delta = min(self.drift_brier_delta, max(0.005, float(watch_brier_delta)))
        self.drift_ece_delta = max(0.02, float(drift_ece_delta))
        self.watch_ece_delta = min(self.drift_ece_delta, max(0.01, float(watch_ece_delta)))
        self.drift_psi = max(0.10, float(drift_psi))
        self.watch_psi = min(self.drift_psi, max(0.05, float(watch_psi)))
        self._report: CalibrationDriftReport | None = None
        self._trend_store = TruthTrendStore(str(self.db_path))

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
    def _psi(reference: list[tuple[float, int]], recent: list[tuple[float, int]]) -> float:
        edges = ProbabilityCalibrationService.BIN_EDGES
        epsilon = 1e-6
        total = 0.0
        for low, high in zip(edges, edges[1:]):
            ref_pct = sum(1 for c, _ in reference if low <= c < high) / max(1, len(reference))
            recent_pct = sum(1 for c, _ in recent if low <= c < high) / max(1, len(recent))
            ref_pct = max(epsilon, ref_pct)
            recent_pct = max(epsilon, recent_pct)
            total += (recent_pct - ref_pct) * math.log(recent_pct / ref_pct)
        return max(0.0, total)

    def evaluate(self, force: bool = False) -> CalibrationDriftReport:
        if self._report is not None and not force:
            return self._report
        rows = self._load_rows()
        if len(rows) < self.min_samples or len(rows) <= self.recent_window + 30:
            self._report = CalibrationDriftReport(
                "INSUFFICIENT_DATA", len(rows), 0, 0,
                0.0, 0.0, 0.0, 0.0, 0.0,
                (f"need at least {self.min_samples} determinate CLOSED PAPER trades",),
            )
            return self._report

        recent_count = min(self.recent_window, max(20, len(rows) // 3))
        reference = rows[:-recent_count]
        recent = rows[-recent_count:]
        calibrator = ProbabilityCalibrationService(db_path=str(self.db_path))
        bins = calibrator._fit_bins(reference)
        predictor = lambda c: calibrator._lookup(c, bins)
        reference_brier, reference_ece = calibrator._metrics(reference, predictor)
        recent_brier, recent_ece = calibrator._metrics(recent, predictor)
        psi = self._psi(reference, recent)

        brier_delta = recent_brier - reference_brier
        ece_delta = recent_ece - reference_ece
        reasons: list[str] = []
        severe = False
        watch = False
        if brier_delta >= self.drift_brier_delta:
            severe = True
            reasons.append(f"Brier degraded by {brier_delta:.4f}")
        elif brier_delta >= self.watch_brier_delta:
            watch = True
            reasons.append(f"Brier watch delta {brier_delta:.4f}")
        if ece_delta >= self.drift_ece_delta:
            severe = True
            reasons.append(f"ECE degraded by {ece_delta:.4f}")
        elif ece_delta >= self.watch_ece_delta:
            watch = True
            reasons.append(f"ECE watch delta {ece_delta:.4f}")
        if psi >= self.drift_psi:
            severe = True
            reasons.append(f"confidence PSI {psi:.4f}")
        elif psi >= self.watch_psi:
            watch = True
            reasons.append(f"confidence PSI watch {psi:.4f}")

        state = "DRIFT" if severe else "WATCH" if watch else "STABLE"
        if not reasons:
            reasons.append("recent PAPER calibration remains within monitored tolerances")
        self._report = CalibrationDriftReport(
            state, len(rows), len(reference), len(recent),
            reference_brier, recent_brier, reference_ece, recent_ece, psi,
            tuple(reasons),
        )
        if force:
            self._trend_store.append("DRIFT", state, {
                "samples": len(rows), "brier_delta": brier_delta,
                "ece_delta": ece_delta, "psi": psi,
            })
        return self._report
