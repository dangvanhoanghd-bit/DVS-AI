from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping
class LifecycleStage(str, Enum):
    UNKNOWN='Unknown'; LIQUIDITY_GRAB='Liquidity Grab'; ACCUMULATION='Accumulation'; SPRING='Spring'; TEST='Test'; MARKUP='Markup'; REACCUMULATION='Reaccumulation'; DISTRIBUTION='Distribution'; UPTHRUST='Upthrust'; MARKDOWN='Markdown'; REDISTRIBUTION='Redistribution'; EXHAUSTION='Exhaustion'; CONTINUATION='Continuation'
@dataclass(frozen=True)
class MicrostructureEvidence:
    score: float
    stage: LifecycleStage|None=None
    phase_quality: float=0.0
    age_bars: int=0
    next_stage: LifecycleStage|None=None
    transition_probability: float=0.0
    explanation: tuple[str,...]=()
    evidence: tuple[str,...]=()
    metadata: Mapping[str,Any]=field(default_factory=lambda: MappingProxyType({}))
    def __post_init__(self):
        object.__setattr__(self,'score',max(0,min(100,float(self.score))))
        object.__setattr__(self,'phase_quality',max(0,min(100,float(self.phase_quality))))
        object.__setattr__(self,'transition_probability',max(0,min(100,float(self.transition_probability))))
        object.__setattr__(self,'age_bars',max(0,int(self.age_bars)))
        object.__setattr__(self,'explanation',tuple(self.explanation or ()))
        object.__setattr__(self,'evidence',tuple(self.evidence or ()))
        object.__setattr__(self,'metadata',MappingProxyType(dict(self.metadata or {})))
