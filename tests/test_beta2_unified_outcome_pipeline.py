from pathlib import Path
import sqlite3

from dvs_ai.services.quantum_data_convergence.models import UnifiedOutcome
from dvs_ai.services.unified_outcome_service import UnifiedOutcomeBuilder


def row(source, sid, outcome, link=None, candidate_id=None, r=1.0):
    provenance = {}
    if link:
        provenance["cross_pipeline_id"] = link
    if candidate_id:
        provenance["candidate_id"] = candidate_id
    return UnifiedOutcome(source, sid, "BTCUSDT", "LONG", "2026-01-01", "2026-01-02", outcome, r, provenance=provenance)


def db_with_snapshot(tmp_path: Path, candidate_id="c1") -> Path:
    db = tmp_path / "x.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE candidate_feature_snapshots(candidate_id TEXT PRIMARY KEY, feature_hash TEXT)")
        con.execute("INSERT INTO candidate_feature_snapshots VALUES(?,?)", (candidate_id, "abc"))
    return db


def test_explicit_same_outcome_is_eligible_with_snapshot(tmp_path):
    b = UnifiedOutcomeBuilder(db_with_snapshot(tmp_path))
    rows = [row("paper_trades", "p1", "WIN", "x", r=1.2), row("candidate_outcomes", "o1", "WIN", "x", "c1", 1.2)]
    out = b.build(rows)
    assert len(out) == 1
    assert out[0].eligibility_status == "UNIFIED_ELIGIBLE"
    assert out[0].feature_snapshot_hash == "abc"


def test_explicit_conflict_is_blocked(tmp_path):
    b = UnifiedOutcomeBuilder(db_with_snapshot(tmp_path))
    out = b.build([row("paper_trades", "p1", "LOSS", "x"), row("candidate_outcomes", "o1", "WIN", "x", "c1")])
    assert out[0].eligibility_status == "CONFLICT"
    assert out[0].conflict_reason == "LOSS vs WIN"


def test_soft_match_never_auto_merges(tmp_path):
    b = UnifiedOutcomeBuilder(db_with_snapshot(tmp_path))
    # identical soft fingerprint, no explicit link
    out = b.build([row("paper_trades", "p1", "WIN"), row("candidate_outcomes", "o1", "WIN", candidate_id="c1")])
    assert len(out) == 1
    assert out[0].eligibility_status == "AMBIGUOUS_MATCH"


def test_terminal_without_snapshot_is_permanently_not_eligible(tmp_path):
    b = UnifiedOutcomeBuilder(tmp_path / "missing.db")
    out = b.build([row("paper_trades", "p1", "WIN", "x"), row("candidate_outcomes", "o1", "WIN", "x", "old")])
    assert out[0].eligibility_status == "NOT_ELIGIBLE"
    assert out[0].eligibility_reason == "HISTORICAL_SNAPSHOT_UNAVAILABLE"


def test_unmatched_source_is_not_eligible(tmp_path):
    b = UnifiedOutcomeBuilder(db_with_snapshot(tmp_path))
    out = b.build([row("candidate_outcomes", "o1", "WIN", candidate_id="c1")])
    assert out[0].identity_status == "UNMATCHED"
    assert out[0].eligibility_status == "NOT_ELIGIBLE"
