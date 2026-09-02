from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from random import Random
from statistics import mean
from typing import Iterable, Tuple


@dataclass(frozen=True)
class ClusterMetric:
    cluster_id: str
    value: float


@dataclass(frozen=True)
class BootstrapInterval:
    estimate: float
    lower: float
    upper: float
    confidence: float
    resamples: int
    cluster_count: int
    valid: bool
    violations: Tuple[str, ...]


def cluster_bootstrap_mean(
    metrics: Iterable[ClusterMetric], *, confidence: float = 0.95,
    resamples: int = 2000, seed: int = 4302,
) -> BootstrapInterval:
    """Reproducible cluster-level percentile bootstrap for the mean."""
    items = tuple(metrics)
    violations: list[str] = []
    if not 0.0 < confidence < 1.0:
        violations.append("INVALID_BOOTSTRAP_CONFIDENCE")
    if resamples < 200:
        violations.append("BOOTSTRAP_RESAMPLES_BELOW_MINIMUM")
    if any(not item.cluster_id.strip() or not isfinite(item.value) for item in items):
        violations.append("INVALID_CLUSTER_METRIC")
    clusters: dict[str, list[float]] = {}
    for item in items:
        clusters.setdefault(item.cluster_id, []).append(item.value)
    if len(clusters) < 2:
        violations.append("INDEPENDENT_CLUSTERS_BELOW_MINIMUM")
    if violations:
        return BootstrapInterval(0.0, 0.0, 0.0, confidence, resamples, len(clusters), False, tuple(violations))

    cluster_values = [mean(values) for _, values in sorted(clusters.items())]
    estimate = mean(cluster_values)
    rng = Random(seed)
    draws = sorted(mean(rng.choices(cluster_values, k=len(cluster_values))) for _ in range(resamples))
    tail = (1.0 - confidence) / 2.0
    lower_index = max(0, min(resamples - 1, int(tail * resamples)))
    upper_index = max(0, min(resamples - 1, int((1.0 - tail) * resamples) - 1))
    return BootstrapInterval(
        estimate=estimate,
        lower=draws[lower_index],
        upper=draws[upper_index],
        confidence=confidence,
        resamples=resamples,
        cluster_count=len(cluster_values),
        valid=True,
        violations=(),
    )
