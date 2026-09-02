from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class StatisticalComparisonResult:
    state: str
    samples: int
    baseline_expectancy: float
    shadow_expectancy: float
    expectancy_delta: float
    ci_low: float
    ci_high: float
    confidence_level: float
    probability_improvement: float
    minimum_detectable_improvement: float
    stable_block_ratio: float
    blocks: int
    reasons: tuple[str, ...]


class ShadowStatisticalComparison:
    """Paired, deterministic bootstrap comparison for observe-only SHADOW evidence.

    Each row represents one market opportunity observed at the same time by MAIN and
    SHADOW. A selected decision receives the observed PAPER outcome; a skipped decision
    receives zero R. This is only valid for paired observations produced by the runtime.
    """

    def __init__(self, *, bootstrap_samples: int = 4000, confidence_level: float = 0.95,
                 minimum_detectable_improvement: float = 0.03, min_samples: int = 40,
                 time_blocks: int = 4, min_stable_block_ratio: float = 0.60,
                 random_seed: int = 2283) -> None:
        self.bootstrap_samples = max(500, int(bootstrap_samples))
        self.confidence_level = min(0.999, max(0.80, float(confidence_level)))
        self.minimum_detectable_improvement = max(0.0, float(minimum_detectable_improvement))
        self.min_samples = max(10, int(min_samples))
        self.time_blocks = max(2, int(time_blocks))
        self.min_stable_block_ratio = min(1.0, max(0.0, float(min_stable_block_ratio)))
        self.random_seed = int(random_seed)

    @staticmethod
    def _selected(decision: Any) -> bool:
        return str(decision or "").upper() in {"READY", "SETUP", "RUNNING", "TRADE"}

    @staticmethod
    def _finite(value: Any) -> float | None:
        try:
            number = float(value)
            return number if math.isfinite(number) else None
        except (TypeError, ValueError):
            return None

    def _paired(self, rows: Iterable[dict[str, Any]]) -> list[tuple[float, float, float]]:
        paired: list[tuple[float, float, float]] = []
        for row in rows:
            outcome = self._finite(row.get("outcome_r"))
            if outcome is None:
                continue
            baseline = outcome if self._selected(row.get("baseline_decision")) else 0.0
            shadow = outcome if self._selected(row.get("shadow_decision")) else 0.0
            paired.append((baseline, shadow, shadow - baseline))
        return paired

    @staticmethod
    def _quantile(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        pos = (len(ordered) - 1) * min(1.0, max(0.0, q))
        low = int(math.floor(pos)); high = int(math.ceil(pos))
        if low == high:
            return ordered[low]
        weight = pos - low
        return ordered[low] * (1.0 - weight) + ordered[high] * weight

    def _block_stability(self, diffs: list[float]) -> tuple[float, int]:
        if not diffs:
            return 0.0, 0
        blocks = min(self.time_blocks, len(diffs))
        positive = 0
        used = 0
        for index in range(blocks):
            start = index * len(diffs) // blocks
            end = (index + 1) * len(diffs) // blocks
            chunk = diffs[start:end]
            if not chunk:
                continue
            used += 1
            if sum(chunk) / len(chunk) >= 0.0:
                positive += 1
        return (positive / used if used else 0.0), used

    def compare(self, rows: Iterable[dict[str, Any]]) -> StatisticalComparisonResult:
        paired = self._paired(rows)
        n = len(paired)
        if n < self.min_samples:
            return StatisticalComparisonResult(
                "INSUFFICIENT_DATA", n, 0.0, 0.0, 0.0, 0.0, 0.0,
                self.confidence_level, 0.0, self.minimum_detectable_improvement,
                0.0, 0, (f"paired samples {n} < {self.min_samples}",),
            )
        baseline_expectancy = sum(x[0] for x in paired) / n
        shadow_expectancy = sum(x[1] for x in paired) / n
        diffs = [x[2] for x in paired]
        delta = sum(diffs) / n

        rng = random.Random(self.random_seed)
        boot: list[float] = []
        for _ in range(self.bootstrap_samples):
            boot.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
        alpha = (1.0 - self.confidence_level) / 2.0
        ci_low = self._quantile(boot, alpha)
        ci_high = self._quantile(boot, 1.0 - alpha)
        probability = sum(1 for value in boot if value > 0.0) / len(boot)
        stable_ratio, blocks = self._block_stability(diffs)

        reasons = [
            f"expectancy_delta={delta:+.4f}",
            f"ci_{int(self.confidence_level * 100)}=[{ci_low:+.4f},{ci_high:+.4f}]",
            f"p_improvement={probability:.3f}",
            f"mdi={self.minimum_detectable_improvement:.4f}",
            f"stable_blocks={stable_ratio:.3f}",
        ]
        if ci_high < 0.0:
            state = "WORSE"
        elif ci_low > 0.0 and delta >= self.minimum_detectable_improvement and stable_ratio >= self.min_stable_block_ratio:
            state = "BETTER"
        elif delta < -self.minimum_detectable_improvement:
            state = "WORSE"
        elif stable_ratio < self.min_stable_block_ratio:
            state = "UNSTABLE"
        else:
            state = "INCONCLUSIVE"
        return StatisticalComparisonResult(
            state, n, baseline_expectancy, shadow_expectancy, delta,
            ci_low, ci_high, self.confidence_level, probability,
            self.minimum_detectable_improvement, stable_ratio, blocks, tuple(reasons),
        )
