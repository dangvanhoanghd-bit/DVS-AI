from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable

from dvs_ai.services.quantum_cross_pipeline_monitor import CrossPipelineMonitor
from dvs_ai.services.quantum_data_convergence.adapter import QuantumDataAdapter
from dvs_ai.services.quantum_data_convergence.models import UnifiedOutcome
from dvs_ai.services.quantum_data_convergence.sources import EpisodeOutcomeSource, PaperTradeSource

TERMINAL_STATUSES = frozenset({"WIN", "LOSS", "INVALID", "AMBIGUOUS", "EXPIRED"})
DETERMINATE_STATUSES = frozenset({"WIN", "LOSS"})


def _sha(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class UnifiedOutcomeRecord:
    unified_id: str
    source_identities: tuple[str, ...]
    candidate_id: str | None
    paper_trade_id: str | None
    symbol: str
    direction: str
    outcome_status: str
    identity_status: str
    eligibility_status: str
    eligibility_reason: str
    feature_snapshot_hash: str | None
    realized_r: float | None
    setup_time: str | None = None
    close_time: str | None = None
    cohort: str | None = None
    regime: str | None = None
    confidence: float | None = None
    entry_score: float | None = None
    risk_score: float | None = None
    rr_planned: float | None = None
    setup_tags: str = ""
    evidence_snapshot: dict | None = None
    conflict_reason: str | None = None
    resolution_source: str | None = None
    review_action: str | None = None
    review_event_sha256: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class UnifiedReviewRepository:
    """Read-only access to the append-only human review ledger."""

    VALID_ACTIONS = frozenset({"ACCEPT_PAPER", "ACCEPT_CANDIDATE", "EXCLUDE"})

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def _events(self) -> list[dict[str, Any]]:
        if not self.db_path.is_file():
            return []
        with sqlite3.connect(self.db_path) as con:
            con.row_factory = sqlite3.Row
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "unified_review_events" not in tables:
                return []
            return [dict(r) for r in con.execute(
                "SELECT * FROM unified_review_events ORDER BY event_id ASC"
            )]

    @staticmethod
    def validate_event(event: dict[str, Any]) -> tuple[bool, str | None]:
        try:
            evidence = json.loads(event.get("evidence_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            return False, "REVIEW_DECISION_INCONSISTENT"
        action = str(event.get("action") or "").upper()
        if action not in UnifiedReviewRepository.VALID_ACTIONS:
            return False, "REVIEW_DECISION_INCONSISTENT"
        if not str(event.get("reviewer") or "").strip() or not str(event.get("reason") or "").strip():
            return False, "REVIEW_DECISION_INCONSISTENT"
        payload = {
            "unified_id": event.get("unified_id"),
            "reviewed_at": event.get("reviewed_at"),
            "reviewer": str(event.get("reviewer") or "").strip(),
            "action": action,
            "reason": str(event.get("reason") or "").strip(),
            "evidence": evidence,
            "previous_status": event.get("previous_status"),
            "resulting_status": event.get("resulting_status"),
        }
        if _sha(payload) != str(event.get("event_sha256") or ""):
            return False, "REVIEW_EVENT_HASH_INVALID"
        return True, None

    def latest_events(self) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        latest: dict[str, dict[str, Any]] = {}
        diagnostics: list[dict[str, Any]] = []
        for event in self._events():
            uid = str(event.get("unified_id") or "")
            valid, code = self.validate_event(event)
            if not valid:
                diagnostics.append({"code": code, "unified_id": uid, "event_id": event.get("event_id")})
                continue
            latest[uid] = event
        return latest, diagnostics


class UnifiedReviewResolver:
    """Applies the latest valid human decision without mutating source history."""

    def __init__(self, repository: UnifiedReviewRepository) -> None:
        self.repository = repository

    def apply(self, records: list[UnifiedOutcomeRecord], raw_rows: list[UnifiedOutcome]) -> tuple[list[UnifiedOutcomeRecord], list[dict[str, Any]]]:
        events, diagnostics = self.repository.latest_events()
        by_uid = {r.unified_id: r for r in records}
        raw_by_identity = {r.identity: r for r in raw_rows}
        for uid in sorted(set(events) - set(by_uid)):
            diagnostics.append({"code": "REVIEW_TARGET_NOT_FOUND", "unified_id": uid, "event_id": events[uid].get("event_id")})

        output: list[UnifiedOutcomeRecord] = []
        for record in records:
            event = events.get(record.unified_id)
            if event is None:
                output.append(record)
                continue
            action = str(event["action"]).upper()
            if action == "EXCLUDE":
                output.append(replace(
                    record, eligibility_status="NOT_ELIGIBLE",
                    eligibility_reason="EXCLUDED_BY_REVIEW", conflict_reason=None,
                    resolution_source="HUMAN_REVIEW", review_action=action,
                    review_event_sha256=str(event["event_sha256"]),
                ))
                continue

            wanted_source = "candidate_outcomes" if action == "ACCEPT_CANDIDATE" else "paper_trades"
            candidates = [raw_by_identity[i] for i in record.source_identities
                          if i in raw_by_identity and raw_by_identity[i].source == wanted_source]
            if not candidates:
                diagnostics.append({"code": "REVIEW_DECISION_INCONSISTENT", "unified_id": record.unified_id,
                                    "event_id": event.get("event_id"), "reason": f"{wanted_source}_source_missing"})
                output.append(record)
                continue
            chosen = candidates[0]
            if chosen.outcome not in TERMINAL_STATUSES:
                diagnostics.append({"code": "REVIEW_DECISION_INCONSISTENT", "unified_id": record.unified_id,
                                    "event_id": event.get("event_id"), "reason": "selected_outcome_non_terminal"})
                output.append(record)
                continue
            if not record.feature_snapshot_hash:
                output.append(replace(
                    record, outcome_status=chosen.outcome, eligibility_status="NOT_ELIGIBLE",
                    eligibility_reason="HISTORICAL_SNAPSHOT_UNAVAILABLE", conflict_reason=None,
                    resolution_source="HUMAN_REVIEW", review_action=action,
                    review_event_sha256=str(event["event_sha256"]),
                ))
                continue
            output.append(replace(
                record, outcome_status=chosen.outcome, eligibility_status="UNIFIED_ELIGIBLE",
                eligibility_reason=f"MANUAL_REVIEW_{action}", conflict_reason=None,
                realized_r=chosen.realized_r if chosen.realized_r is not None else record.realized_r,
                resolution_source="HUMAN_REVIEW", review_action=action,
                review_event_sha256=str(event["event_sha256"]),
            ))
        return sorted(output, key=lambda r: r.unified_id), diagnostics


class UnifiedOutcomeBuilder:
    """Builds governed records above the read-only convergence adapter.

    CrossPipelineMonitor remains observe-only. Only explicit cross-source links
    may be auto-merged. Soft fingerprints are review-only and never eligible.
    """

    def __init__(
        self,
        db_path: str | Path,
        cancel_check: Callable[[str], bool] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.monitor = CrossPipelineMonitor()
        self.cancel_check = cancel_check

    def _check_cancel(self, stage: str) -> bool:
        callback = self.cancel_check
        if callback is None:
            return False
        try:
            return bool(callback(stage))
        except Exception:
            return False

    def _snapshot_hash(
        self,
        candidate_id: str | None,
        conn_state: dict | None = None,
    ) -> str | None:
        if self._check_cancel("builder_snapshot_hash_enter"):
            return None
        if not candidate_id:
            return None
        # RC6.12B: reuse one SQLite connection + one schema read across an
        # entire build() call instead of opening a fresh connection and
        # re-querying sqlite_master for every single record. conn_state is
        # a small mutable dict owned by the calling build() invocation;
        # the connection is opened lazily on first actual need here, so a
        # build() that never needs a snapshot lookup still never touches
        # SQLite at all -- matching the previous per-call behavior exactly.
        if conn_state is None:
            # Fallback path (e.g. called outside build()): behave exactly
            # as before, one connection for this single lookup only.
            if not self.db_path.is_file():
                return None
            with sqlite3.connect(self.db_path) as con:
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "candidate_feature_snapshots" not in tables:
                    return None
                row = con.execute(
                    "SELECT feature_hash FROM candidate_feature_snapshots WHERE candidate_id=? LIMIT 1",
                    (candidate_id,),
                ).fetchone()
            return str(row[0]) if row and row[0] else None

        conn_state["snapshot_hash_calls"] = conn_state.get("snapshot_hash_calls", 0) + 1
        if not conn_state.get("opened"):
            conn_state["opened"] = True
            if self.db_path.is_file():
                con = sqlite3.connect(self.db_path)
                conn_state["con"] = con
                conn_state["sqlite_connections_opened"] = conn_state.get("sqlite_connections_opened", 0) + 1
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                conn_state["schema_queries"] = conn_state.get("schema_queries", 0) + 1
                conn_state["has_snapshot_table"] = "candidate_feature_snapshots" in tables
        con = conn_state.get("con")
        if con is None or not conn_state.get("has_snapshot_table"):
            return None
        row = con.execute(
            "SELECT feature_hash FROM candidate_feature_snapshots WHERE candidate_id=? LIMIT 1",
            (candidate_id,),
        ).fetchone()
        conn_state["feature_hash_queries"] = conn_state.get("feature_hash_queries", 0) + 1
        return str(row[0]) if row and row[0] else None

    @staticmethod
    def _candidate_id(rows: Iterable[UnifiedOutcome]) -> str | None:
        for row in rows:
            value = row.provenance.get("candidate_id")
            if value not in (None, ""):
                return str(value)
        return None

    @staticmethod
    def _paper_id(rows: Iterable[UnifiedOutcome]) -> str | None:
        for row in rows:
            if row.source == "paper_trades":
                return str(row.source_id)
        return None

    def _record(self, rows: list[UnifiedOutcome], identity_status: str,
                eligibility_status: str, reason: str,
                outcome: str | None = None, conflict: str | None = None,
                conn_state: dict | None = None) -> UnifiedOutcomeRecord:
        rows = sorted(rows, key=lambda r: r.identity)
        candidate_id = self._candidate_id(rows)
        snapshot_hash = self._snapshot_hash(candidate_id, conn_state)
        chosen = next((r for r in rows if r.source == "candidate_outcomes"), rows[0])
        paper = next((r for r in rows if r.source == "paper_trades"), None)
        def first_value(name: str):
            primary = getattr(chosen, name, None)
            if primary not in (None, ""):
                return primary
            return getattr(paper, name, None) if paper is not None else None
        evidence = chosen.evidence_snapshot or (paper.evidence_snapshot if paper is not None else None)
        tags = str(chosen.provenance.get("setup_tags", "") or "")
        if not tags and paper is not None:
            tags = str(paper.provenance.get("setup_tags", "") or "")
        final_outcome = outcome or chosen.outcome
        if eligibility_status == "UNIFIED_ELIGIBLE" and not snapshot_hash:
            eligibility_status = "NOT_ELIGIBLE"
            reason = "HISTORICAL_SNAPSHOT_UNAVAILABLE"
        payload = {
            "identities": [r.identity for r in rows],
            "outcome": final_outcome,
            "identity_status": identity_status,
            "snapshot": snapshot_hash,
        }
        return UnifiedOutcomeRecord(
            unified_id=_sha(payload),
            source_identities=tuple(r.identity for r in rows),
            candidate_id=candidate_id,
            paper_trade_id=self._paper_id(rows),
            symbol=chosen.symbol,
            direction=chosen.direction,
            outcome_status=final_outcome,
            identity_status=identity_status,
            eligibility_status=eligibility_status,
            eligibility_reason=reason,
            feature_snapshot_hash=snapshot_hash,
            realized_r=first_value("realized_r"),
            setup_time=str(first_value("setup_time") or "") or None,
            close_time=str(first_value("close_time") or "") or None,
            cohort=str(first_value("cohort") or "") or None,
            regime=str(first_value("regime") or "") or None,
            confidence=first_value("confidence"),
            entry_score=first_value("entry_score"),
            risk_score=first_value("risk_score"),
            rr_planned=first_value("rr_planned"),
            setup_tags=tags,
            evidence_snapshot=dict(evidence) if evidence is not None else None,
            conflict_reason=conflict,
        )

    def build(self, rows: Iterable[UnifiedOutcome]) -> list[UnifiedOutcomeRecord]:
        if self._check_cancel("builder_materialize_enter"):
            return []
        materialized = list(rows)
        if self._check_cancel("builder_monitor_enter"):
            return []
        report = self.monitor.inspect(materialized)
        if self._check_cancel("builder_monitor_exit"):
            return []
        by_identity = {r.identity: r for r in materialized}
        consumed: set[str] = set()
        output: list[UnifiedOutcomeRecord] = []

        # RC6.12B: one shared, lazily-opened SQLite connection + one schema
        # read for this entire build() call, instead of _snapshot_hash()
        # opening a fresh connection and re-querying sqlite_master for
        # every single record. See _snapshot_hash() for the exact
        # fallback/short-circuit semantics this preserves.
        _conn_state: dict = {}
        _build_started_ns = time.monotonic_ns()
        # RC6.12B-r1: pessimistic default. Only overwritten to "NORMAL" or
        # "CANCELLED" right before the matching return statement below, so
        # if an exception propagates out of this try block instead (e.g. a
        # sqlite error inside _snapshot_hash), termination_reason simply
        # stays "EXCEPTION" -- correctly distinguishing that case from a
        # normal completion, without adding any new except clause or
        # changing what the exception itself does.
        _termination_reason = "EXCEPTION"
        try:
            # Explicit links are the only automatic merge authority.
            for overlap in report.exact_link_overlaps:
                if self._check_cancel("builder_exact_overlap"):
                    _termination_reason = "CANCELLED"
                    return sorted(records, key=lambda r: r.unified_id)
                grouped = [by_identity[i] for i in overlap.identities]
                consumed.update(overlap.identities)
                outcomes = {r.outcome for r in grouped}
                if len(outcomes) != 1:
                    output.append(self._record(
                        grouped, "EXPLICIT", "CONFLICT", "TERMINAL_OUTCOME_CONFLICT",
                        conflict=" vs ".join(sorted(outcomes)),
                        conn_state=_conn_state,
                    ))
                    continue
                outcome = next(iter(outcomes))
                eligible = outcome in TERMINAL_STATUSES
                output.append(self._record(
                    grouped, "EXPLICIT",
                    "UNIFIED_ELIGIBLE" if eligible else "NOT_ELIGIBLE",
                    "TERMINAL_WITH_EXPLICIT_IDENTITY" if eligible else "NON_TERMINAL_OUTCOME",
                    outcome=outcome,
                    conn_state=_conn_state,
                ))

            # Soft matches remain advisory/manual-review only.
            for overlap in report.potential_overlaps:
                if self._check_cancel("builder_potential_overlap"):
                    _termination_reason = "CANCELLED"
                    return sorted(records, key=lambda r: r.unified_id)
                remaining = [by_identity[i] for i in overlap.identities if i not in consumed]
                if not remaining:
                    continue
                consumed.update(r.identity for r in remaining)
                output.append(self._record(
                    remaining, "SOFT_FINGERPRINT", "AMBIGUOUS_MATCH",
                    "MANUAL_REVIEW_REQUIRED", conflict="SOFT_FINGERPRINT_REVIEW_ONLY",
                    conn_state=_conn_state,
                ))

            # Unmatched terminal rows are preserved but not learning/quantum eligible.
            for row in materialized:
                if self._check_cancel("builder_unmatched_row"):
                    _termination_reason = "CANCELLED"
                    return sorted(records, key=lambda r: r.unified_id)
                if row.identity in consumed:
                    continue
                output.append(self._record(
                    [row], "UNMATCHED", "NOT_ELIGIBLE", "UNMATCHED_SOURCE_IDENTITY",
                    conn_state=_conn_state,
                ))
            _termination_reason = "NORMAL"
            return sorted(output, key=lambda r: r.unified_id)
        finally:
            _shared_con = _conn_state.get("con")
            if _shared_con is not None:
                try:
                    _shared_con.close()
                except Exception:
                    pass
            try:
                from .learning_snapshot_builder_forensics import (
                    record_builder_build,
                )
                record_builder_build(
                    input_rows=len(materialized),
                    snapshot_hash_calls=_conn_state.get("snapshot_hash_calls", 0),
                    sqlite_connections_opened=_conn_state.get("sqlite_connections_opened", 0),
                    schema_queries=_conn_state.get("schema_queries", 0),
                    feature_hash_queries=_conn_state.get("feature_hash_queries", 0),
                    build_elapsed_ms=round((time.monotonic_ns() - _build_started_ns) / 1_000_000.0, 3),
                    cancelled=(_termination_reason == "CANCELLED"),
                    termination_reason=_termination_reason,
                )
            except Exception:
                pass


class UnifiedOutcomeService:
    """Single governed read model for Learning, Quantum and Governance."""

    def __init__(self, db_path: str | Path = "data/dvs_paper_trades.db",
                 review_db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.review_db_path = Path(review_db_path) if review_db_path is not None else Path("data/unified_review_ledger.db")
        self._cancel_check: Callable[[str], bool] | None = None
        self.adapter = QuantumDataAdapter(
            PaperTradeSource(self.db_path), EpisodeOutcomeSource(self.db_path)
        )
        self.builder = UnifiedOutcomeBuilder(self.db_path, self._check_cancel)
        self.review_repository = UnifiedReviewRepository(self.review_db_path)
        self.review_resolver = UnifiedReviewResolver(self.review_repository)
        self._review_diagnostics: list[dict[str, Any]] = []

    def set_cancel_check(
        self,
        callback: Callable[[str], bool] | None,
    ) -> None:
        self._cancel_check = callback

    def _check_cancel(self, stage: str) -> bool:
        callback = self._cancel_check
        if callback is None:
            return False
        try:
            return bool(callback(stage))
        except Exception:
            return False

    def records(self) -> list[UnifiedOutcomeRecord]:
        if self._check_cancel("records_adapter_enter"):
            return []
        raw = list(self.adapter.read_terminal())
        if self._check_cancel("records_adapter_exit"):
            return []
        base = self.builder.build(raw)
        if self._check_cancel("records_builder_exit"):
            return base
        resolved, diagnostics = self.review_resolver.apply(base, raw)
        if self._check_cancel("records_review_exit"):
            return resolved
        self._review_diagnostics = diagnostics
        return resolved

    def review_diagnostics(self) -> list[dict[str, Any]]:
        self.records()
        return [dict(item) for item in self._review_diagnostics]

    def eligible(self) -> list[UnifiedOutcomeRecord]:
        return [r for r in self.records() if r.eligibility_status == "UNIFIED_ELIGIBLE"]

    def learning_ready(self) -> list[UnifiedOutcomeRecord]:
        return [r for r in self.eligible() if r.outcome_status in DETERMINATE_STATUSES]


    def pipeline_schema_available(self) -> bool:
        if not self.db_path.is_file():
            return False
        with sqlite3.connect(self.db_path) as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {"paper_trades", "setup_episodes", "decision_candidates", "candidate_outcomes"}.issubset(tables)

    def legacy_compat_learning_ready(self) -> list[UnifiedOutcomeRecord]:
        """Deprecated compatibility for pre-unified databases only.

        This never runs when the Beta 2 pipeline schema exists. It is retained
        solely for old isolated databases/tests during Deprecate → Audit → Remove.
        """
        from .legacy_path_telemetry import emit_legacy_sql_path_used
        if self.pipeline_schema_available():
            return []
        emit_legacy_sql_path_used(__name__, "UnifiedOutcomeService.legacy_compat_learning_ready", "PRE_UNIFIED_DATABASE")
        rows = PaperTradeSource(self.db_path).read_terminal()
        output = []
        for row in rows:
            if row.outcome not in DETERMINATE_STATUSES:
                continue
            payload = {"legacy": row.identity, "outcome": row.outcome}
            output.append(UnifiedOutcomeRecord(
                unified_id=_sha(payload), source_identities=(row.identity,), candidate_id=None,
                paper_trade_id=str(row.source_id), symbol=row.symbol, direction=row.direction,
                outcome_status=row.outcome, identity_status="LEGACY_COMPAT",
                eligibility_status="LEARNING_READY_COMPAT", eligibility_reason="PRE_UNIFIED_DATABASE",
                feature_snapshot_hash=_sha(row.evidence_snapshot) if row.evidence_snapshot else None,
                realized_r=row.realized_r, setup_time=row.setup_time, close_time=row.close_time,
                cohort=row.cohort, regime=row.regime, confidence=row.confidence,
                entry_score=row.entry_score, risk_score=row.risk_score, rr_planned=row.rr_planned,
                setup_tags=str(row.provenance.get("setup_tags", "")),
                evidence_snapshot=dict(row.evidence_snapshot) if row.evidence_snapshot else None,
            ))
        return output

    def statistics(self) -> dict:
        rows = self.records()
        eligible = [r for r in rows if r.eligibility_status == "UNIFIED_ELIGIBLE"]
        learning = [r for r in eligible if r.outcome_status in DETERMINATE_STATUSES]
        outcomes = Counter(r.outcome_status for r in learning)
        gross_win = sum(float(r.realized_r or 0) for r in learning if float(r.realized_r or 0) > 0)
        gross_loss = abs(sum(float(r.realized_r or 0) for r in learning if float(r.realized_r or 0) < 0))
        return {
            "total_unified": len(rows),
            "unified_eligible": len(eligible),
            "learning_ready": len(learning),
            "wins": outcomes.get("WIN", 0),
            "losses": outcomes.get("LOSS", 0),
            "conflicts": sum(r.eligibility_status == "CONFLICT" for r in rows),
            "ambiguous_matches": sum(r.eligibility_status == "AMBIGUOUS_MATCH" for r in rows),
            "not_eligible": sum(r.eligibility_status == "NOT_ELIGIBLE" for r in rows),
            "win_rate": (outcomes.get("WIN", 0) / len(learning) * 100.0) if learning else 0.0,
            "avg_r": (sum(float(r.realized_r or 0) for r in learning) / len(learning)) if learning else 0.0,
            "profit_factor": (gross_win / gross_loss) if gross_loss else (float("inf") if gross_win else 0.0),
        }
