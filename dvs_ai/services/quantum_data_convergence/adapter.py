from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .models import UnifiedOutcome
from .sources import OutcomeSource


@dataclass(frozen=True)
class ConvergenceReport:
    total: int
    by_source: dict[str, int]
    by_outcome: dict[str, int]
    duplicate_identities: tuple[str, ...]


class QuantumDataAdapter:
    """Read-only convergence adapter.

    QBP-0 intentionally performs no migration and no heuristic cross-source
    deduplication. Source-qualified identities prevent accidental collisions.
    """

    def __init__(self, *sources: OutcomeSource) -> None:
        self.sources = tuple(sources)

    def read_terminal(self) -> list[UnifiedOutcome]:
        rows = [row for source in self.sources for row in source.read_terminal()]
        rows.sort(key=lambda r: (r.close_time or r.setup_time, r.identity))
        identities = [r.identity for r in rows]
        if len(identities) != len(set(identities)):
            duplicates = sorted(k for k, v in Counter(identities).items() if v > 1)
            raise ValueError(f"duplicate source-qualified identities: {duplicates}")
        return rows

    def report(self, rows: Iterable[UnifiedOutcome] | None = None) -> ConvergenceReport:
        materialized = list(self.read_terminal() if rows is None else rows)
        identities = [r.identity for r in materialized]
        duplicates = tuple(sorted(k for k, v in Counter(identities).items() if v > 1))
        return ConvergenceReport(
            total=len(materialized),
            by_source=dict(sorted(Counter(r.source for r in materialized).items())),
            by_outcome=dict(sorted(Counter(r.outcome for r in materialized).items())),
            duplicate_identities=duplicates,
        )
