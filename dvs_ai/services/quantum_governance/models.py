from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Tuple


class GovernanceState(str, Enum):
    READY_FOR_AUDIT = "READY_FOR_AUDIT"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class GovernanceRequest:
    study_id: str
    policy_scope_id: str
    policy_scope_hash: str
    decision_engine_checksum: str
    expected_decision_engine_checksum: str
    dataset_manifest: Mapping[str, Any]
    replay_manifest: Mapping[str, Any]
    explanation_manifest: Mapping[str, Any]
    validation_manifest: Mapping[str, Any]
    attempt_ledger_path: Path
    holdout_ledger_path: Path
    holdout_id: str


@dataclass(frozen=True)
class GovernanceResult:
    state: GovernanceState
    study_id: str
    violations: Tuple[str, ...]
    checks: Mapping[str, bool]
    manifest: Mapping[str, Any]
    optimizer_allowed: bool = False
    recommendation_allowed: bool = False
    shadow_apply_allowed: bool = False
    main_write_authority: bool = False
    trade_execution_authority: bool = False
