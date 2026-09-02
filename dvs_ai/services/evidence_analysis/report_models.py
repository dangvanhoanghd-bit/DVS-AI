from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class StageState(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    ANALYSIS_ABORTED = "ANALYSIS_ABORTED"

@dataclass(frozen=True)
class IntegrityReport:
    state: StageState
    checks: tuple[tuple[str, str], ...]
    reasons: tuple[str, ...]

@dataclass(frozen=True)
class EvidenceReport:
    state: StageState
    sample_count: int
    selected_count: int
    outcome_count: int
    expectancy: float | None
    win_rate: float | None
    chronology_blocks: tuple[float, ...]
    reason: str = ""
    selected_outcomes: tuple[float, ...] = ()
    artifact_hash: str = ""

@dataclass(frozen=True)
class ConfidenceReport:
    state: StageState
    conclusion_state: str
    confidence_level: str
    ci_low: float | None
    ci_high: float | None
    reason: str
    probability_positive: float | None = None
    interval_width: float | None = None
    outcome_count: int = 0
    engine_version: str = "1.0"

@dataclass(frozen=True)
class GapItem:
    dimension: str
    current: int
    required: int
    missing: int
    eta_days: float | None

@dataclass(frozen=True)
class ActionableGapReport:
    state: StageState
    gaps: tuple[GapItem, ...]
    reason: str
    velocity_per_day: float | None = None
    eta_reliable: bool = False

@dataclass(frozen=True)
class RecommendationResult:
    state: StageState
    recommendation: str
    reason: str
    actionable: bool

@dataclass(frozen=True)
class EvidenceAnalysisResult:
    protocol_version: str
    context_id: str
    integrity: IntegrityReport
    evidence: EvidenceReport
    confidence: ConfidenceReport
    gap: ActionableGapReport
    recommendation: RecommendationResult
