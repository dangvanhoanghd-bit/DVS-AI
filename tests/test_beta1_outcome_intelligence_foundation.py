import sqlite3

import pytest

from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore
from dvs_ai.services.outcome_intelligence import OutcomeIntelligenceService


def seed_candidate(db_path):
    store = OutcomeInfrastructureStore(db_path)
    episode = store.create_episode(
        symbol="BTC/USDT", direction="LONG", decision_engine_profile_hash="d"*64,
        trade_plan_profile_hash="p"*64, setup_fingerprint="f"*64, primary_zone_id=1,
        structural_event_id="NONE", lifecycle_family="FORMING", evaluated_at="2026-07-23 00:00:00",
        evaluation_id="eval-1", gate_set=(),
    )
    store.append_evaluation(
        episode_id=episode, evaluation_id="eval-1", evaluated_at="2026-07-23 00:00:00",
        entry_score=50, confidence=60, opportunity_score=55, gate_set=(),
    )
    cid = store.activate_candidate(
        episode_id=episode, evaluation_id="eval-1", activated_at="2026-07-23 00:00:00",
        symbol="BTC/USDT", direction="LONG", decision_hash="d"*64, plan_hash="p"*64,
        gate_set=(), entry_low=99, entry_high=101, invalidation=95, tp1=105, tp2=110,
    )
    return cid


def test_snapshot_is_immutable_and_idempotent(tmp_path):
    db = tmp_path / "paper.db"
    cid = seed_candidate(db)
    svc = OutcomeIntelligenceService(db)
    h1 = svc.capture_feature_snapshot(candidate_id=cid, evaluation_id="eval-1", features={"rsi15m": 55.2, "cmf15m": 0.1})
    h2 = svc.capture_feature_snapshot(candidate_id=cid, evaluation_id="eval-1", features={"cmf15m": 0.1, "rsi15m": 55.2})
    assert h1 == h2
    with pytest.raises(ValueError, match="immutable"):
        svc.capture_feature_snapshot(candidate_id=cid, evaluation_id="eval-1", features={"rsi15m": 99})


def test_pending_outcome_is_not_learning_ready(tmp_path):
    db = tmp_path / "paper.db"
    cid = seed_candidate(db)
    svc = OutcomeIntelligenceService(db, minimum_samples=1)
    svc.capture_feature_snapshot(candidate_id=cid, evaluation_id="eval-1", features={"rsi15m": 55.2})
    summary = svc.maturity_summary()
    assert summary.pending == 1
    assert summary.resolved == 0
    assert summary.learning_ready == 0
    assert summary.readiness_state == "LEARNING_NOT_READY"
    assert svc.build_dataset() == []


def test_resolved_outcome_builds_reproducible_dataset(tmp_path):
    db = tmp_path / "paper.db"
    cid = seed_candidate(db)
    svc = OutcomeIntelligenceService(db, minimum_samples=1)
    svc.capture_feature_snapshot(candidate_id=cid, evaluation_id="eval-1", features={"rsi15m": 55.2, "direction": "LONG"})
    with sqlite3.connect(db) as con:
        con.execute("""UPDATE candidate_outcomes SET status='WIN',outcome_detail='TP2',outcome_time='2026-07-23 01:00:00',realized_r=2.0,mfe_r=2.4,mae_r=-0.3 WHERE candidate_id=?""", (cid,))
    first = svc.build_dataset()
    second = svc.build_dataset()
    assert first == second
    assert len(first) == 1
    assert first[0]["status"] == "WIN"
    assert first[0]["features"]["rsi15m"] == "55.20000000"
    assert svc.maturity_summary().readiness_state == "LEARNING_READY"


def test_resolved_without_snapshot_is_excluded(tmp_path):
    db = tmp_path / "paper.db"
    cid = seed_candidate(db)
    svc = OutcomeIntelligenceService(db, minimum_samples=1)
    with sqlite3.connect(db) as con:
        con.execute("UPDATE candidate_outcomes SET status='LOSS',outcome_time='2026-07-23 01:00:00' WHERE candidate_id=?", (cid,))
    assert svc.maturity_summary().resolved == 1
    assert svc.maturity_summary().learning_ready == 0
    assert svc.build_dataset() == []


def test_empty_export_is_explicit_and_does_not_create_files(tmp_path):
    from dvs_ai.services.outcome_intelligence import NoLearningSamplesError

    db = tmp_path / "paper.db"
    seed_candidate(db)
    svc = OutcomeIntelligenceService(db)
    jsonl = tmp_path / "out" / "dataset.jsonl"
    csv_path = tmp_path / "out" / "dataset.csv"
    with pytest.raises(NoLearningSamplesError):
        svc.export_jsonl(jsonl)
    with pytest.raises(NoLearningSamplesError):
        svc.export_csv(csv_path)
    assert not jsonl.exists()
    assert not csv_path.exists()
