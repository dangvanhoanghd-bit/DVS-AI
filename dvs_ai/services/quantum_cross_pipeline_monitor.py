from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from dvs_ai.services.quantum_data_convergence.models import UnifiedOutcome


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PotentialOverlap:
    fingerprint: str
    identities: tuple[str, ...]
    sources: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class CrossPipelineReport:
    total: int
    by_source: dict[str, int]
    exact_link_overlaps: tuple[PotentialOverlap, ...]
    potential_overlaps: tuple[PotentialOverlap, ...]
    action: str
    generated_at: str
    self_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CrossPipelineMonitor:
    """Observe-only duplicate-risk monitor; it never merges or deletes rows."""

    @staticmethod
    def _explicit_link(row: UnifiedOutcome) -> str | None:
        for key in ("cross_pipeline_id", "candidate_id", "outcome_id", "decision_id", "signal_id", "setup_fingerprint"):
            value = row.provenance.get(key)
            if value not in (None, ""):
                return f"{key}:{value}"
        return None

    @staticmethod
    def _soft_fingerprint(row: UnifiedOutcome) -> str:
        payload = {
            "symbol": str(row.symbol).upper(),
            "direction": str(row.direction).upper(),
            "setup_time": str(row.setup_time),
            "close_time": str(row.close_time or ""),
            "outcome": row.outcome,
            "realized_r": None if row.realized_r is None else round(float(row.realized_r), 8),
        }
        return _hash(payload)

    def inspect(self, rows: Iterable[UnifiedOutcome]) -> CrossPipelineReport:
        materialized = list(rows)
        exact: dict[str, list[UnifiedOutcome]] = defaultdict(list)
        soft: dict[str, list[UnifiedOutcome]] = defaultdict(list)
        for row in materialized:
            link = self._explicit_link(row)
            if link:
                exact[link].append(row)
            soft[self._soft_fingerprint(row)].append(row)

        def make(groups: dict[str, list[UnifiedOutcome]], reason: str) -> tuple[PotentialOverlap, ...]:
            found = []
            for fingerprint, grouped in groups.items():
                sources = sorted({row.source for row in grouped})
                if len(sources) < 2:
                    continue
                found.append(PotentialOverlap(
                    fingerprint=fingerprint,
                    identities=tuple(sorted(row.identity for row in grouped)),
                    sources=tuple(sources),
                    reason=reason,
                ))
            return tuple(sorted(found, key=lambda item: item.fingerprint))

        exact_rows = make(exact, "EXPLICIT_CROSS_SOURCE_LINK")
        exact_identities = {identity for item in exact_rows for identity in item.identities}
        potential_rows = tuple(
            item for item in make(soft, "SOFT_FINGERPRINT_REVIEW_ONLY")
            if not set(item.identities).issubset(exact_identities)
        )
        generated_at = datetime.now(timezone.utc).isoformat()
        action = "REVIEW_REQUIRED" if exact_rows or potential_rows else "NO_OVERLAP_DETECTED"
        by_source = dict(sorted(Counter(r.source for r in materialized).items()))
        payload = {
            "total": len(materialized),
            "by_source": by_source,
            "exact_link_overlaps": [asdict(item) for item in exact_rows],
            "potential_overlaps": [asdict(item) for item in potential_rows],
            "action": action,
            "generated_at": generated_at,
        }
        return CrossPipelineReport(
            total=len(materialized),
            by_source=by_source,
            exact_link_overlaps=exact_rows,
            potential_overlaps=potential_rows,
            action=action,
            generated_at=generated_at,
            self_sha256=_hash(payload),
        )
