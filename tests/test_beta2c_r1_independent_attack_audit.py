from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from dvs_ai.services.quantum_data_convergence.models import UnifiedOutcome
from dvs_ai.services.unified_integrity_service import (
    UnifiedIntegrityAuditor,
    UnifiedReleaseGate,
    UnifiedReviewLedger,
)
from dvs_ai.services.unified_outcome_service import (
    UnifiedOutcomeBuilder,
    UnifiedOutcomeService,
)


def raw(source: str, sid: str, outcome: str, link: str | None = None,
        candidate_id: str | None = None, realized_r: float = 1.0,
        setup_time: str = "2026-01-01T00:00:00Z") -> UnifiedOutcome:
    provenance = {}
    if link is not None:
        provenance["cross_pipeline_id"] = link
    if candidate_id is not None:
        provenance["candidate_id"] = candidate_id
    return UnifiedOutcome(
        source, sid, "BTCUSDT", "LONG", setup_time, "2026-01-02T00:00:00Z",
        outcome, realized_r, provenance=provenance,
    )


def runtime_db(tmp_path: Path, snapshots: tuple[tuple[str, str], ...] = (("c1", "snap-1"),)) -> Path:
    db = tmp_path / "runtime.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE candidate_feature_snapshots(candidate_id TEXT PRIMARY KEY, feature_hash TEXT)")
        con.executemany("INSERT INTO candidate_feature_snapshots VALUES(?,?)", snapshots)
    return db


class StaticAdapter:
    def __init__(self, rows):
        self.rows = list(rows)
    def read_terminal(self):
        return list(self.rows)


def service(tmp_path: Path, rows, snapshots=(("c1", "snap-1"),)):
    db = runtime_db(tmp_path, snapshots)
    review_db = tmp_path / "reviews.db"
    svc = UnifiedOutcomeService(db, review_db_path=review_db)
    svc.adapter = StaticAdapter(rows)
    return svc, UnifiedReviewLedger(review_db)


def conflict_rows():
    return [
        raw("paper_trades", "p1", "LOSS", "x", realized_r=-1.0),
        raw("candidate_outcomes", "o1", "WIN", "x", "c1", 2.0),
    ]


def test_01_soft_fingerprint_never_auto_merges_or_learns(tmp_path):
    # Same fingerprint but no explicit cross_pipeline_id.
    rows = [
        raw("paper_trades", "p1", "WIN", None),
        raw("candidate_outcomes", "o1", "WIN", None, "c1"),
    ]
    svc, _ = service(tmp_path, rows)
    records = svc.records()
    assert len(records) == 1
    assert records[0].identity_status == "SOFT_FINGERPRINT"
    assert records[0].eligibility_status == "AMBIGUOUS_MATCH"
    assert svc.learning_ready() == []


def test_02_tp1_hit_is_non_terminal_and_not_eligible(tmp_path):
    rows = [
        raw("paper_trades", "p1", "TP1_HIT", "x"),
        raw("candidate_outcomes", "o1", "TP1_HIT", "x", "c1"),
    ]
    svc, _ = service(tmp_path, rows)
    record = svc.records()[0]
    assert record.outcome_status == "TP1_HIT"
    assert record.eligibility_status == "NOT_ELIGIBLE"
    assert svc.learning_ready() == []


def test_03_terminal_without_snapshot_remains_permanently_ineligible(tmp_path):
    rows = [
        raw("paper_trades", "p1", "WIN", "x"),
        raw("candidate_outcomes", "o1", "WIN", "x", "c1"),
    ]
    svc, ledger = service(tmp_path, rows, snapshots=())
    record = svc.records()[0]
    assert record.eligibility_reason == "HISTORICAL_SNAPSHOT_UNAVAILABLE"
    ledger.review(record, "auditor", "ACCEPT_CANDIDATE", "manual evidence")
    reviewed = svc.records()[0]
    assert reviewed.eligibility_status == "NOT_ELIGIBLE"
    assert reviewed.eligibility_reason == "HISTORICAL_SNAPSHOT_UNAVAILABLE"


def test_04_conflict_requires_human_and_is_blocked_before_review(tmp_path):
    svc, _ = service(tmp_path, conflict_rows())
    record = svc.records()[0]
    assert record.eligibility_status == "CONFLICT"
    assert svc.learning_ready() == []


def test_05_accept_candidate_reaches_all_governed_views(tmp_path):
    svc, ledger = service(tmp_path, conflict_rows())
    ledger.review(svc.records()[0], "auditor", "ACCEPT_CANDIDATE", "candidate verified")
    record = svc.records()[0]
    assert record.outcome_status == "WIN"
    assert record.realized_r == 2.0
    assert record.eligibility_status == "UNIFIED_ELIGIBLE"
    assert svc.eligible()[0].unified_id == record.unified_id
    assert svc.learning_ready()[0].unified_id == record.unified_id
    assert svc.statistics()["learning_ready"] == 1


def test_06_accept_paper_reaches_all_governed_views(tmp_path):
    svc, ledger = service(tmp_path, conflict_rows())
    ledger.review(svc.records()[0], "auditor", "ACCEPT_PAPER", "paper verified")
    record = svc.records()[0]
    assert record.outcome_status == "LOSS"
    assert record.realized_r == -1.0
    assert svc.learning_ready()[0].outcome_status == "LOSS"


def test_07_exclude_is_visible_and_never_learning_ready(tmp_path):
    svc, ledger = service(tmp_path, conflict_rows())
    ledger.review(svc.records()[0], "auditor", "EXCLUDE", "irreconcilable")
    record = svc.records()[0]
    assert record.eligibility_reason == "EXCLUDED_BY_REVIEW"
    assert record.review_action == "EXCLUDE"
    assert svc.learning_ready() == []


def test_08_latest_valid_review_wins_and_history_is_append_only(tmp_path):
    svc, ledger = service(tmp_path, conflict_rows())
    record = svc.records()[0]
    ledger.review(record, "a", "ACCEPT_PAPER", "first")
    ledger.review(record, "b", "ACCEPT_CANDIDATE", "second")
    assert len(ledger.history(record.unified_id)) == 2
    assert svc.records()[0].review_action == "ACCEPT_CANDIDATE"


def test_09_tampered_event_does_not_apply_and_blocks_release(tmp_path):
    svc, ledger = service(tmp_path, conflict_rows())
    ledger.review(svc.records()[0], "auditor", "ACCEPT_CANDIDATE", "verified")
    with sqlite3.connect(ledger.db_path) as con:
        con.execute("UPDATE unified_review_events SET event_sha256='tampered'")
    record = svc.records()[0]
    assert record.eligibility_status == "CONFLICT"
    report = UnifiedIntegrityAuditor(svc).audit()
    assert report.counts["REVIEW_EVENT_HASH_INVALID"] == 1
    assert UnifiedReleaseGate(UnifiedIntegrityAuditor(svc), tmp_path / "none.jsonl").evaluate()["gate"] == "BLOCKED"


def test_10_review_target_not_found_blocks_release(tmp_path):
    svc, ledger = service(tmp_path, conflict_rows())
    orphan = replace(svc.records()[0], unified_id="orphan")
    ledger.review(orphan, "auditor", "EXCLUDE", "orphan")
    report = UnifiedIntegrityAuditor(svc).audit()
    assert report.counts["REVIEW_TARGET_NOT_FOUND"] == 1
    assert report.release_ready is False


def test_11_inconsistent_source_selection_does_not_apply(tmp_path):
    rows = [raw("candidate_outcomes", "o1", "WIN", "x", "c1")]
    svc, ledger = service(tmp_path, rows)
    record = svc.records()[0]
    ledger.review(record, "auditor", "ACCEPT_PAPER", "paper claimed")
    after = svc.records()[0]
    assert after.eligibility_status == "NOT_ELIGIBLE"
    assert any(d["code"] == "REVIEW_DECISION_INCONSISTENT" for d in svc.review_diagnostics())


def test_12_clean_reviewed_pipeline_passes_integrity_and_gate(tmp_path):
    svc, ledger = service(tmp_path, conflict_rows())
    ledger.review(svc.records()[0], "auditor", "ACCEPT_CANDIDATE", "verified")
    report = UnifiedIntegrityAuditor(svc).audit()
    assert report.release_ready is True
    assert report.counts == {}
    gate = UnifiedReleaseGate(UnifiedIntegrityAuditor(svc), tmp_path / "none.jsonl").evaluate()
    assert gate["gate"] == "PASS"
