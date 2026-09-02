from __future__ import annotations

from datetime import datetime
from typing import Iterable, List

from .models import WalkForwardFold

ALLOWED_SPLITS = frozenset({"ANCHORED_WALK_FORWARD", "ROLLING_WALK_FORWARD"})


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return parsed


def validate_walk_forward(split_method: str, folds: Iterable[WalkForwardFold]) -> List[str]:
    violations: List[str] = []
    if split_method not in ALLOWED_SPLITS:
        violations.append("RANDOM_SPLIT_FORBIDDEN" if "RANDOM" in split_method.upper() else "INVALID_PROTOCOL")
        return violations

    previous_holdout_end = None
    for fold in folds:
        try:
            train_start = _dt(fold.train_start)
            train_end = _dt(fold.train_end)
            validation_start = _dt(fold.validation_start)
            validation_end = _dt(fold.validation_end)
            holdout_start = _dt(fold.holdout_start)
            holdout_end = _dt(fold.holdout_end)
        except (TypeError, ValueError):
            violations.append(f"{fold.fold_id}:TIME_ORDER_VIOLATION")
            continue

        if not (train_start <= train_end < validation_start <= validation_end < holdout_start <= holdout_end):
            violations.append(f"{fold.fold_id}:TIME_ORDER_VIOLATION")
            continue

        purge_gap = (validation_start - train_end).total_seconds()
        embargo_gap = (holdout_start - validation_end).total_seconds()
        if purge_gap < max(0, fold.purge_seconds) or embargo_gap < max(0, fold.embargo_seconds):
            violations.append(f"{fold.fold_id}:PURGE_EMBARGO_VIOLATION")

        if previous_holdout_end is not None and train_start <= previous_holdout_end:
            # Fold chronology may be anchored, but future holdout data must never enter a later train window.
            violations.append(f"{fold.fold_id}:HOLDOUT_LEAKAGE")
        previous_holdout_end = holdout_end
    return violations
