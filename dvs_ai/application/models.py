from __future__ import annotations

from dataclasses import dataclass

from dvs_ai.scientific.decision import ScientificDecision
from dvs_ai.strategy_intelligence import FusedSignal, MarketSnapshot
from dvs_ai.trading import PaperOrder


@dataclass(frozen=True, slots=True)
class UnifiedCycleRequest:
    pipeline_run_id: str
    snapshot: MarketSnapshot
    quantity: float

    def __post_init__(self) -> None:
        if not self.pipeline_run_id.strip():
            raise ValueError("pipeline_run_id is required")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


@dataclass(frozen=True, slots=True)
class UnifiedCycleResult:
    request: UnifiedCycleRequest
    fused_signal: FusedSignal
    decision: ScientificDecision
    order: PaperOrder
    event_names: tuple[str, ...]
    succeeded: bool
