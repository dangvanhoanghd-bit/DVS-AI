from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Tuple


@dataclass(frozen=True)
class HypothesisTest:
    hypothesis_id: str
    p_value: float


@dataclass(frozen=True)
class CorrectedHypothesis:
    hypothesis_id: str
    raw_p_value: float
    adjusted_p_value: float
    rejected: bool
    rank: int


@dataclass(frozen=True)
class MultipleComparisonResult:
    method: str
    family_alpha: float
    hypothesis_count: int
    rejected_count: int
    tests: Tuple[CorrectedHypothesis, ...]
    valid: bool
    violations: Tuple[str, ...]


def holm_bonferroni(tests: Iterable[HypothesisTest], family_alpha: float = 0.05) -> MultipleComparisonResult:
    """Deterministic Holm-Bonferroni family-wise error control.

    Empty families are valid because some validation attempts are constraint-only.
    Invalid identifiers, duplicate identifiers, or p-values outside [0, 1] fail closed.
    """
    items = tuple(tests)
    violations: list[str] = []
    if not isfinite(family_alpha) or not 0.0 < family_alpha < 1.0:
        violations.append("INVALID_FAMILY_ALPHA")
    ids = [item.hypothesis_id for item in items]
    if any(not value.strip() for value in ids):
        violations.append("EMPTY_HYPOTHESIS_ID")
    if len(ids) != len(set(ids)):
        violations.append("DUPLICATE_HYPOTHESIS_ID")
    if any(not isfinite(item.p_value) or not 0.0 <= item.p_value <= 1.0 for item in items):
        violations.append("INVALID_P_VALUE")
    if violations:
        return MultipleComparisonResult("HOLM_BONFERRONI", family_alpha, len(items), 0, (), False, tuple(violations))

    ordered = sorted(items, key=lambda item: (item.p_value, item.hypothesis_id))
    m = len(ordered)
    adjusted: list[CorrectedHypothesis] = []
    running_max = 0.0
    still_rejecting = True
    for index, item in enumerate(ordered, start=1):
        multiplier = m - index + 1
        adjusted_p = min(1.0, max(running_max, multiplier * item.p_value))
        running_max = adjusted_p
        threshold = family_alpha / multiplier if multiplier else family_alpha
        rejected = still_rejecting and item.p_value <= threshold
        if not rejected:
            still_rejecting = False
        adjusted.append(CorrectedHypothesis(
            hypothesis_id=item.hypothesis_id,
            raw_p_value=item.p_value,
            adjusted_p_value=adjusted_p,
            rejected=rejected,
            rank=index,
        ))
    return MultipleComparisonResult(
        method="HOLM_BONFERRONI",
        family_alpha=family_alpha,
        hypothesis_count=m,
        rejected_count=sum(1 for item in adjusted if item.rejected),
        tests=tuple(adjusted),
        valid=True,
        violations=(),
    )
