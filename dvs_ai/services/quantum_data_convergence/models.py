from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class UnifiedOutcome:
    """Canonical, read-only outcome record used above storage backends.

    The record preserves source vocabulary and provenance.  It does not grant
    optimizer, shadow-write, MAIN-write, or execution authority.
    """

    source: str
    source_id: str
    symbol: str
    direction: str
    setup_time: str
    close_time: str | None
    outcome: str
    realized_r: float | None
    confidence: float | None = None
    entry_score: float | None = None
    risk_score: float | None = None
    rr_planned: float | None = None
    cohort: str | None = None
    regime: str | None = None
    evidence_snapshot: Mapping[str, Any] | None = None
    original_status: str | None = None
    original_result: str | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def identity(self) -> str:
        return f"{self.source}:{self.source_id}"
