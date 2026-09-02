from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import median
from typing import Iterable, Tuple


@dataclass(frozen=True)
class StabilityObservation:
    observation_id: str
    metric_value: float
    fold_id: str
    regime_id: str
    symbol: str
    parameter_distance: int = 0


@dataclass(frozen=True)
class StabilityResult:
    valid: bool
    stable: bool
    observation_count: int
    fold_count: int
    regime_count: int
    symbol_count: int
    sign_consistency: float
    neighborhood_consistency: float
    median_metric: float
    violations: Tuple[str, ...]


def evaluate_stability(
    observations: Iterable[StabilityObservation],
    *,
    minimum_observations: int = 3,
    minimum_folds: int = 2,
    minimum_regimes: int = 2,
    minimum_symbols: int = 2,
    minimum_sign_consistency: float = 0.70,
    minimum_neighborhood_consistency: float = 0.60,
) -> StabilityResult:
    """Evaluate historical robustness without making causal claims.

    A zero metric is neutral and does not count as a supporting sign. Parameter
    neighborhood observations are those with non-zero parameter_distance.
    """
    items = tuple(observations)
    violations: list[str] = []
    if any(not isfinite(item.metric_value) for item in items):
        violations.append("NON_FINITE_STABILITY_METRIC")
    ids = [item.observation_id for item in items]
    if any(not value.strip() for value in ids) or len(ids) != len(set(ids)):
        violations.append("INVALID_STABILITY_OBSERVATION_ID")
    for threshold in (minimum_sign_consistency, minimum_neighborhood_consistency):
        if not isfinite(threshold) or not 0.0 <= threshold <= 1.0:
            violations.append("INVALID_STABILITY_THRESHOLD")
    if violations:
        return StabilityResult(False, False, len(items), 0, 0, 0, 0.0, 0.0, 0.0, tuple(sorted(set(violations))))

    values = [item.metric_value for item in items]
    center = median(values) if values else 0.0
    target_sign = 1 if center > 0 else -1 if center < 0 else 0
    supporting = sum(1 for value in values if target_sign and ((value > 0) == (target_sign > 0)))
    sign_consistency = supporting / len(values) if values else 0.0

    neighbors = [item.metric_value for item in items if item.parameter_distance != 0]
    neighbor_supporting = sum(1 for value in neighbors if target_sign and ((value > 0) == (target_sign > 0)))
    neighborhood_consistency = neighbor_supporting / len(neighbors) if neighbors else 0.0

    fold_count = len({item.fold_id for item in items if item.fold_id})
    regime_count = len({item.regime_id for item in items if item.regime_id})
    symbol_count = len({item.symbol for item in items if item.symbol})

    if len(items) < minimum_observations:
        violations.append("STABILITY_OBSERVATIONS_BELOW_MINIMUM")
    if fold_count < minimum_folds:
        violations.append("FOLD_COVERAGE_BELOW_MINIMUM")
    if regime_count < minimum_regimes:
        violations.append("REGIME_COVERAGE_BELOW_MINIMUM")
    if symbol_count < minimum_symbols:
        violations.append("SYMBOL_COVERAGE_BELOW_MINIMUM")
    if target_sign == 0 or sign_consistency < minimum_sign_consistency:
        violations.append("SIGN_STABILITY_BELOW_MINIMUM")
    if not neighbors or neighborhood_consistency < minimum_neighborhood_consistency:
        violations.append("PARAMETER_NEIGHBORHOOD_UNSTABLE")

    return StabilityResult(
        valid=True,
        stable=not violations,
        observation_count=len(items),
        fold_count=fold_count,
        regime_count=regime_count,
        symbol_count=symbol_count,
        sign_consistency=sign_consistency,
        neighborhood_consistency=neighborhood_consistency,
        median_metric=center,
        violations=tuple(violations),
    )
