from __future__ import annotations

import sqlite3
from pathlib import Path

from dvs_ai.services.quantum_data_convergence.models import UnifiedOutcome
from dvs_ai.services.unified_integrity_service import UnifiedIntegrityAuditor, UnifiedReleaseGate, UnifiedReviewLedger
from dvs_ai.services.unified_outcome_service import (
    UnifiedOutcomeBuilder, UnifiedReviewRepository, UnifiedReviewResolver,
)


def raw(source: str, sid: str, outcome: str, link: str, candidate_id: str | None = None, realized_r: float = 1.0):
    provenance = {"cross_pipeline_id": link}
    if candidate_id:
        provenance["candidate_id"] = candidate_id
    return UnifiedOutcome(
        source, sid, "BTCUSDT", "LONG", "2026-01-01", "2026-01-02",
        outcome, realized_r, provenance=provenance,
    )


def snapshot_db(tmp_path: Path, include: bool = True) -> Path:
    db = tmp_path / "runtime.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE candidate_feature_snapshots(candidate_id TEXT PRIMARY KEY, feature_hash TEXT)")
        if include:
            con.execute("INSERT INTO candidate_feature_snapshots VALUES('c1','snap-hash')")
    return db


def build_conflict(tmp_path: Path, include_snapshot: bool = True):
    db = snapshot_db(tmp_path, include_snapshot)
    rows = [raw("paper_trades", "p1", "LOSS", "x", realized_r=-1.0),
            raw("candidate_outcomes", "o1", "WIN", "x", "c1", 2.0)]
    record = UnifiedOutcomeBuilder(db).build(rows)[0]
    return db, rows, record


def resolve(ledger_path: Path, record, rows):
    return UnifiedReviewResolver(UnifiedReviewRepository(ledger_path)).apply([record], rows)


def test_accept_candidate_changes_conflict_to_eligible(tmp_path):
    _, rows, record = build_conflict(tmp_path)
    ledger = UnifiedReviewLedger(tmp_path / "reviews.db")
    ledger.review(record, "auditor", "ACCEPT_CANDIDATE", "candidate evidence verified")
    resolved, diagnostics = resolve(ledger.db_path, record, rows)
    assert diagnostics == []
    assert resolved[0].eligibility_status == "UNIFIED_ELIGIBLE"
    assert resolved[0].outcome_status == "WIN"
    assert resolved[0].eligibility_reason == "MANUAL_REVIEW_ACCEPT_CANDIDATE"
    assert resolved[0].resolution_source == "HUMAN_REVIEW"


def test_accept_candidate_without_snapshot_stays_not_eligible(tmp_path):
    _, rows, record = build_conflict(tmp_path, include_snapshot=False)
    ledger = UnifiedReviewLedger(tmp_path / "reviews.db")
    ledger.review(record, "auditor", "ACCEPT_CANDIDATE", "candidate accepted")
    resolved, diagnostics = resolve(ledger.db_path, record, rows)
    assert diagnostics == []
    assert resolved[0].eligibility_status == "NOT_ELIGIBLE"
    assert resolved[0].eligibility_reason == "HISTORICAL_SNAPSHOT_UNAVAILABLE"


def test_accept_paper_selects_paper_outcome(tmp_path):
    _, rows, record = build_conflict(tmp_path)
    ledger = UnifiedReviewLedger(tmp_path / "reviews.db")
    ledger.review(record, "auditor", "ACCEPT_PAPER", "paper evidence verified")
    resolved, _ = resolve(ledger.db_path, record, rows)
    assert resolved[0].eligibility_status == "UNIFIED_ELIGIBLE"
    assert resolved[0].outcome_status == "LOSS"
    assert resolved[0].eligibility_reason == "MANUAL_REVIEW_ACCEPT_PAPER"


def test_exclude_is_terminal_and_not_learning_eligible(tmp_path):
    _, rows, record = build_conflict(tmp_path)
    ledger = UnifiedReviewLedger(tmp_path / "reviews.db")
    ledger.review(record, "auditor", "EXCLUDE", "evidence irreconcilable")
    resolved, _ = resolve(ledger.db_path, record, rows)
    assert resolved[0].eligibility_status == "NOT_ELIGIBLE"
    assert resolved[0].eligibility_reason == "EXCLUDED_BY_REVIEW"
    assert resolved[0].conflict_reason is None


def test_latest_valid_review_event_wins(tmp_path):
    _, rows, record = build_conflict(tmp_path)
    ledger = UnifiedReviewLedger(tmp_path / "reviews.db")
    ledger.review(record, "a", "ACCEPT_PAPER", "first review")
    ledger.review(record, "b", "ACCEPT_CANDIDATE", "new evidence")
    resolved, _ = resolve(ledger.db_path, record, rows)
    assert resolved[0].outcome_status == "WIN"
    assert resolved[0].review_action == "ACCEPT_CANDIDATE"


def test_tampered_review_hash_is_rejected_and_reported(tmp_path):
    _, rows, record = build_conflict(tmp_path)
    ledger = UnifiedReviewLedger(tmp_path / "reviews.db")
    ledger.review(record, "auditor", "ACCEPT_CANDIDATE", "verified")
    with sqlite3.connect(ledger.db_path) as con:
        con.execute("UPDATE unified_review_events SET event_sha256='tampered'")
    resolved, diagnostics = resolve(ledger.db_path, record, rows)
    assert resolved[0].eligibility_status == "CONFLICT"
    assert diagnostics[0]["code"] == "REVIEW_EVENT_HASH_INVALID"


def test_review_target_not_found_is_reported(tmp_path):
    _, rows, record = build_conflict(tmp_path)
    ledger = UnifiedReviewLedger(tmp_path / "reviews.db")
    ledger.review(record, "auditor", "EXCLUDE", "exclude")
    with sqlite3.connect(ledger.db_path) as con:
        con.execute("UPDATE unified_review_events SET unified_id='missing'")
        event = dict(con.execute("SELECT * FROM unified_review_events").fetchone()) if False else None
    # Changing unified_id invalidates hash, so create a valid orphan by copying and recomputing through a fake record.
    from dataclasses import replace
    orphan = replace(record, unified_id="missing")
    ledger2 = UnifiedReviewLedger(tmp_path / "orphan.db")
    ledger2.review(orphan, "auditor", "EXCLUDE", "orphan target")
    _, diagnostics = resolve(ledger2.db_path, record, rows)
    assert any(d["code"] == "REVIEW_TARGET_NOT_FOUND" for d in diagnostics)


class FeedbackService:
    def __init__(self, rows, repository, diagnostics):
        self._rows = rows
        self.review_repository = repository
        self._diagnostics = diagnostics
    def records(self): return list(self._rows)
    def learning_ready(self):
        return [r for r in self._rows if r.eligibility_status == "UNIFIED_ELIGIBLE" and r.outcome_status in {"WIN", "LOSS"}]
    def review_diagnostics(self): return list(self._diagnostics)


def test_integrity_and_release_gate_block_invalid_review(tmp_path):
    _, rows, record = build_conflict(tmp_path)
    ledger = UnifiedReviewLedger(tmp_path / "reviews.db")
    ledger.review(record, "auditor", "ACCEPT_CANDIDATE", "verified")
    with sqlite3.connect(ledger.db_path) as con:
        con.execute("UPDATE unified_review_events SET event_sha256='bad'")
    repository = UnifiedReviewRepository(ledger.db_path)
    resolved, diagnostics = UnifiedReviewResolver(repository).apply([record], rows)
    service = FeedbackService(resolved, repository, diagnostics)
    report = UnifiedIntegrityAuditor(service).audit()
    assert report.counts["REVIEW_EVENT_HASH_INVALID"] == 1
    assert report.release_ready is False
    gate = UnifiedReleaseGate(UnifiedIntegrityAuditor(service), tmp_path / "none.jsonl").evaluate()
    assert gate["gate"] == "BLOCKED"

class StaticAdapter:
    def __init__(self, rows): self._rows = list(rows)
    def read_terminal(self): return list(self._rows)


def test_unified_outcome_service_applies_review_for_all_consumers(tmp_path):
    from dvs_ai.services.unified_outcome_service import UnifiedOutcomeService
    db, rows, record = build_conflict(tmp_path)
    review_db = tmp_path / "reviews.db"
    ledger = UnifiedReviewLedger(review_db)
    ledger.review(record, "auditor", "ACCEPT_CANDIDATE", "verified")
    service = UnifiedOutcomeService(db, review_db_path=review_db)
    service.adapter = StaticAdapter(rows)
    records = service.records()
    assert records[0].eligibility_status == "UNIFIED_ELIGIBLE"
    assert service.eligible()[0].unified_id == records[0].unified_id
    assert service.learning_ready()[0].outcome_status == "WIN"
    stats = service.statistics()
    assert stats["unified_eligible"] == 1
    assert stats["learning_ready"] == 1
