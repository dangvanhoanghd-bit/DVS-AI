from dataclasses import replace

import pytest

from dvs_ai.services.unified_integrity_service import (
    UnifiedIntegrityAuditor, UnifiedReleaseGate, UnifiedReviewLedger,
)
from dvs_ai.services.unified_outcome_service import UnifiedOutcomeRecord


class StubService:
    def __init__(self, rows): self._rows = list(rows)
    def records(self): return list(self._rows)
    def learning_ready(self):
        return [r for r in self._rows if r.eligibility_status == "UNIFIED_ELIGIBLE" and r.outcome_status in {"WIN", "LOSS"}]


def record(**changes):
    base = UnifiedOutcomeRecord(
        unified_id="u1", source_identities=("paper_trades:1", "candidate_outcomes:1"),
        candidate_id="c1", paper_trade_id="1", symbol="BTCUSDT", direction="LONG",
        outcome_status="WIN", identity_status="EXPLICIT", eligibility_status="UNIFIED_ELIGIBLE",
        eligibility_reason="TERMINAL_WITH_EXPLICIT_IDENTITY", feature_snapshot_hash="abc",
        realized_r=1.5,
    )
    return replace(base, **changes)


def test_clean_report_passes():
    report = UnifiedIntegrityAuditor(StubService([record()])).audit()
    assert report.release_ready is True
    assert report.integrity_score == 100.0
    assert report.findings == ()


def test_eligible_without_snapshot_is_critical():
    report = UnifiedIntegrityAuditor(StubService([record(feature_snapshot_hash=None)])).audit()
    assert report.release_ready is False
    assert report.counts["ELIGIBLE_WITHOUT_SNAPSHOT"] == 1


def test_duplicate_source_identity_is_blocker():
    a = record(unified_id="u1")
    b = record(unified_id="u2")
    report = UnifiedIntegrityAuditor(StubService([a, b])).audit()
    assert report.counts["DUPLICATE_EXPLICIT_LINK"] == 2


def test_review_ledger_is_append_only(tmp_path):
    ledger = UnifiedReviewLedger(tmp_path / "reviews.db")
    blocked = record(eligibility_status="CONFLICT", conflict_reason="WIN vs LOSS")
    event = ledger.review(blocked, "auditor", "ACCEPT_CANDIDATE", "candidate evidence verified", {"ticket": "R-1"})
    assert event["resulting_status"] == "MANUALLY_APPROVED"
    history = ledger.history(blocked.unified_id)
    assert len(history) == 1
    assert history[0]["action"] == "ACCEPT_CANDIDATE"
    assert history[0]["evidence"] == {"ticket": "R-1"}


def test_review_rejects_eligible_record(tmp_path):
    ledger = UnifiedReviewLedger(tmp_path / "reviews.db")
    with pytest.raises(ValueError):
        ledger.review(record(), "auditor", "EXCLUDE", "not allowed")


def test_release_gate_blocks_legacy_telemetry(tmp_path):
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text('{"event":"LEGACY_SQL_PATH_USED"}\n', encoding="utf-8")
    gate = UnifiedReleaseGate(UnifiedIntegrityAuditor(StubService([record()])), telemetry).evaluate()
    assert gate["gate"] == "BLOCKED"
    assert gate["legacy_sql_calls"] == 1
