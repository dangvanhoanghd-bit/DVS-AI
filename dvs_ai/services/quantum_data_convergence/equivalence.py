from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .mapping import OutcomeMappingError, map_legacy_outcome
from .models import UnifiedOutcome
from .sources import PaperTradeSource, _readonly_connection


@dataclass(frozen=True)
class EquivalenceDifference:
    identity: str
    field: str
    legacy_value: Any
    adapter_value: Any


@dataclass(frozen=True)
class OutcomeStatistics:
    count: int
    wins: int
    losses: int
    ambiguous: int
    expired_unfilled: int
    sum_realized_r: float
    mean_realized_r: float | None


@dataclass(frozen=True)
class DataEquivalenceReport:
    state: str
    legacy_count: int
    adapter_count: int
    legacy_digest: str
    adapter_digest: str
    legacy_statistics: OutcomeStatistics
    adapter_statistics: OutcomeStatistics
    differences: tuple[EquivalenceDifference, ...]
    skipped_unsupported_legacy_rows: int

    @property
    def equivalent(self) -> bool:
        return self.state == "EQUIVALENT"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LegacyPaperTradeBaselineReader:
    """Independent read-only baseline for QBP-0D regression comparison.

    It deliberately does not call PaperTradeSource.  The centralized mapping
    policy is shared, while SQL selection and materialization remain separate
    so adapter field-loss/order defects can be detected.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.skipped_unsupported = 0

    def read_terminal(self) -> list[dict[str, Any]]:
        self.skipped_unsupported = 0
        if not self.db_path.is_file():
            return []
        with _readonly_connection(self.db_path) as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "paper_trades" not in tables:
                return []
            columns = {r[1] for r in con.execute("PRAGMA table_info(paper_trades)")}

            def expr(name: str, fallback: str = "NULL") -> str:
                return name if name in columns else fallback

            rows = con.execute(f"""
                SELECT id,created_at,{expr('closed_at')} AS closed_at,
                       {expr('symbol', "''")} AS symbol,{expr('direction', "''")} AS direction,
                       status,result,{expr('r_multiple')} AS r_multiple,
                       {expr('confidence')} AS confidence,{expr('entry_score')} AS entry_score,
                       {expr('risk_score')} AS risk_score,{expr('rr_planned')} AS rr_planned,
                       {expr('lab')} AS lab,{expr('regime')} AS regime,
                       {expr('setup_tags', "''")} AS setup_tags
                FROM paper_trades
                WHERE status='CLOSED'
                ORDER BY created_at ASC,id ASC
            """).fetchall()

        materialized: list[dict[str, Any]] = []
        for row in rows:
            try:
                mapped = map_legacy_outcome(
                    status=row["status"], result=row["result"], realized_r=row["r_multiple"]
                )
            except OutcomeMappingError:
                self.skipped_unsupported += 1
                continue
            materialized.append({
                "identity": f"paper_trades:{row['id']}",
                "source_id": str(row["id"]),
                "symbol": str(row["symbol"]),
                "direction": str(row["direction"]),
                "setup_time": str(row["created_at"]),
                "close_time": str(row["closed_at"]) if row["closed_at"] else None,
                "outcome": mapped.unified,
                "realized_r": float(row["r_multiple"]) if row["r_multiple"] is not None else None,
                "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
                "entry_score": float(row["entry_score"]) if row["entry_score"] is not None else None,
                "risk_score": float(row["risk_score"]) if row["risk_score"] is not None else None,
                "rr_planned": float(row["rr_planned"]) if row["rr_planned"] is not None else None,
                "cohort": str(row["lab"]) if row["lab"] is not None else None,
                "regime": str(row["regime"]) if row["regime"] is not None else None,
                "original_status": mapped.original_status,
                "original_result": mapped.original_result,
                "mapping_rule_id": mapped.rule_id,
                "setup_tags": str(row["setup_tags"] or ""),
            })
        return materialized


def _canonical_adapter(row: UnifiedOutcome) -> dict[str, Any]:
    return {
        "identity": row.identity,
        "source_id": row.source_id,
        "symbol": row.symbol,
        "direction": row.direction,
        "setup_time": row.setup_time,
        "close_time": row.close_time,
        "outcome": row.outcome,
        "realized_r": row.realized_r,
        "confidence": row.confidence,
        "entry_score": row.entry_score,
        "risk_score": row.risk_score,
        "rr_planned": row.rr_planned,
        "cohort": row.cohort,
        "regime": row.regime,
        "original_status": row.original_status,
        "original_result": row.original_result,
        "mapping_rule_id": row.provenance.get("mapping_rule_id"),
        "setup_tags": str(row.provenance.get("setup_tags", "")),
    }


def _digest(rows: Iterable[dict[str, Any]]) -> str:
    payload = json.dumps(list(rows), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stats(rows: Iterable[dict[str, Any]]) -> OutcomeStatistics:
    materialized = list(rows)
    finite_r = [float(r["realized_r"]) for r in materialized
                if r.get("realized_r") is not None and math.isfinite(float(r["realized_r"]))]
    return OutcomeStatistics(
        count=len(materialized),
        wins=sum(r["outcome"] == "WIN" for r in materialized),
        losses=sum(r["outcome"] == "LOSS" for r in materialized),
        ambiguous=sum(r["outcome"] == "AMBIGUOUS" for r in materialized),
        expired_unfilled=sum(r["outcome"] == "EXPIRED_UNFILLED" for r in materialized),
        sum_realized_r=sum(finite_r),
        mean_realized_r=(sum(finite_r) / len(finite_r)) if finite_r else None,
    )


class DataEquivalenceVerifier:
    """Compare direct legacy semantics with the new PaperTradeSource adapter."""

    FIELDS = (
        "source_id", "symbol", "direction", "setup_time", "close_time", "outcome",
        "realized_r", "confidence", "entry_score", "risk_score", "rr_planned",
        "cohort", "regime", "original_status", "original_result", "mapping_rule_id",
        "setup_tags",
    )

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def verify(self) -> DataEquivalenceReport:
        baseline_reader = LegacyPaperTradeBaselineReader(self.db_path)
        legacy = baseline_reader.read_terminal()
        adapted = [_canonical_adapter(r) for r in PaperTradeSource(self.db_path).read_terminal()]
        legacy_by_id = {r["identity"]: r for r in legacy}
        adapted_by_id = {r["identity"]: r for r in adapted}
        differences: list[EquivalenceDifference] = []

        for identity in sorted(set(legacy_by_id) | set(adapted_by_id)):
            left = legacy_by_id.get(identity)
            right = adapted_by_id.get(identity)
            if left is None:
                differences.append(EquivalenceDifference(identity, "record", None, "PRESENT"))
                continue
            if right is None:
                differences.append(EquivalenceDifference(identity, "record", "PRESENT", None))
                continue
            for field in self.FIELDS:
                if left.get(field) != right.get(field):
                    differences.append(EquivalenceDifference(identity, field, left.get(field), right.get(field)))

        legacy_sorted = [legacy_by_id[k] for k in sorted(legacy_by_id)]
        adapter_sorted = [adapted_by_id[k] for k in sorted(adapted_by_id)]
        legacy_stats = _stats(legacy_sorted)
        adapter_stats = _stats(adapter_sorted)
        state = "EQUIVALENT" if not differences and legacy_stats == adapter_stats else "MISMATCH"
        return DataEquivalenceReport(
            state=state,
            legacy_count=len(legacy_sorted),
            adapter_count=len(adapter_sorted),
            legacy_digest=_digest(legacy_sorted),
            adapter_digest=_digest(adapter_sorted),
            legacy_statistics=legacy_stats,
            adapter_statistics=adapter_stats,
            differences=tuple(differences),
            skipped_unsupported_legacy_rows=baseline_reader.skipped_unsupported,
        )
