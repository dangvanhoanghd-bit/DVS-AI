from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Tuple


class ValidationState(str, Enum):
    PASS = "PASS"
    BLOCK = "BLOCK"


class ValidationBlockCode(str, Enum):
    INVALID_PROTOCOL = "INVALID_PROTOCOL"
    RANDOM_SPLIT_FORBIDDEN = "RANDOM_SPLIT_FORBIDDEN"
    TIME_ORDER_VIOLATION = "TIME_ORDER_VIOLATION"
    PURGE_EMBARGO_VIOLATION = "PURGE_EMBARGO_VIOLATION"
    EFFECTIVE_N_BELOW_MINIMUM = "EFFECTIVE_N_BELOW_MINIMUM"
    HOLDOUT_ALREADY_CONSUMED = "HOLDOUT_ALREADY_CONSUMED"
    HOLDOUT_NOT_LOCKED = "HOLDOUT_NOT_LOCKED"
    REPLAY_NOT_VERIFIED = "REPLAY_NOT_VERIFIED"
    POLICY_SCOPE_MISMATCH = "POLICY_SCOPE_MISMATCH"
    DECISION_CHECKSUM_MISMATCH = "DECISION_CHECKSUM_MISMATCH"
    ATTEMPT_LEDGER_INVALID = "ATTEMPT_LEDGER_INVALID"
    MULTIPLE_COMPARISON_INVALID = "MULTIPLE_COMPARISON_INVALID"
    STABILITY_NOT_DEMONSTRATED = "STABILITY_NOT_DEMONSTRATED"
    BOOTSTRAP_INVALID = "BOOTSTRAP_INVALID"


@dataclass(frozen=True)
class WalkForwardFold:
    fold_id: str
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    holdout_start: str
    holdout_end: str
    purge_seconds: int
    embargo_seconds: int


@dataclass(frozen=True)
class ValidationRequest:
    study_id: str
    policy_scope_id: str
    policy_scope_hash: str
    decision_engine_checksum: str
    replay_state: str
    effective_n: float
    minimum_effective_n: float
    split_method: str
    folds: Tuple[WalkForwardFold, ...]
    holdout_id: str
    candidate_count: int = 1
    family_alpha: float = 0.05
    hypothesis_tests: Tuple[Any, ...] = ()
    stability_observations: Tuple[Any, ...] = ()
    bootstrap_metrics: Tuple[Any, ...] = ()
    require_statistical_diagnostics: bool = False
    burn_in_eligible_outcomes: int = -1
    burn_in_required_capabilities: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationResult:
    state: ValidationState
    study_id: str
    violations: Tuple[str, ...]
    checks: Mapping[str, bool]
    manifest: Mapping[str, Any]
    optimizer_allowed: bool = False
    recommendation_allowed: bool = False
    shadow_apply_allowed: bool = False
    main_write_authority: bool = False
