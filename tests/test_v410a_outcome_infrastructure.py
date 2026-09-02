from __future__ import annotations

import sqlite3
from pathlib import Path

from dvs_ai.services.outcome_infrastructure import (
    OutcomeInfrastructureStore, canonical_hash, trade_plan_profile_hash,
    zone_identity, valid_trade_plan,
)
from dvs_ai.services.setup_episode_service import EvaluationCapture, SetupEpisodeService


def test_canonical_hash_is_order_and_float_stable():
    assert canonical_hash({"b": 0.4, "a": 1}) == canonical_hash({"a": 1, "b": 0.40000000000000002})
    assert trade_plan_profile_hash({"maximum_entry_wait_bars": 8}) != trade_plan_profile_hash({"maximum_entry_wait_bars": 12})


def test_zone_bucket_and_trade_plan_validation():
    a, bucket = zone_identity(100.0, 2.0)
    b, _ = zone_identity(100.4, 2.0)
    assert a == b
    assert bucket == 1.0
    assert valid_trade_plan(direction="LONG", entry_low=99, entry_high=100, invalidation=98, tp1=102, tp2=104)
    assert not valid_trade_plan(direction="WAIT", entry_low=99, entry_high=100, invalidation=98, tp1=102, tp2=104)


def _capture(ts: str, evaluation_id: str, **overrides):
    data = dict(
        symbol="BTCUSDT", direction="LONG", evaluated_at=ts,
        entry_score=55, confidence=52, opportunity_score=60,
        gate_set=("CONFIDENCE_LT_68",), decision_engine_profile_hash="d" * 64,
        level=100.0, atr_15m=2.0, lifecycle="EARLY_FORMATION",
        entry_low=99.0, entry_high=100.0, invalidation=98.0, tp1=102.0, tp2=104.0,
        evaluation_id=evaluation_id,
    )
    data.update(overrides)
    return EvaluationCapture(**data)


def test_repeated_evaluations_create_one_episode_and_one_candidate(tmp_path: Path):
    store = OutcomeInfrastructureStore(tmp_path / "paper.db")
    service = SetupEpisodeService(store)
    episode1, candidate1 = service.capture(_capture("2026-07-20 10:00:00", "e1"))
    episode2, candidate2 = service.capture(_capture("2026-07-20 10:15:00", "e2"))
    assert episode1 == episode2
    assert candidate1 is not None
    assert candidate2 is None
    with store.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM setup_episodes").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM decision_candidates").fetchone()[0] == 1
        assert con.execute("SELECT evaluation_count FROM setup_episodes").fetchone()[0] == 2


def test_activation_waits_for_first_valid_trade_plan(tmp_path: Path):
    store = OutcomeInfrastructureStore(tmp_path / "paper.db")
    service = SetupEpisodeService(store)
    episode, candidate = service.capture(_capture("2026-07-20 10:00:00", "e1", entry_low=None))
    assert candidate is None
    episode2, candidate2 = service.capture(_capture("2026-07-20 10:15:00", "e2"))
    assert episode == episode2
    assert candidate2 is not None
    with store.connect() as con:
        row = con.execute("SELECT setup_episodes.activation_evaluation_id,decision_candidates.entry_expiry_at FROM setup_episodes JOIN decision_candidates USING(candidate_id)").fetchone()
    assert row[0] == "e2"
    assert row[1] == "2026-07-20 12:15:00"


def test_gap_or_direction_creates_new_episode(tmp_path: Path):
    store = OutcomeInfrastructureStore(tmp_path / "paper.db")
    service = SetupEpisodeService(store)
    e1, _ = service.capture(_capture("2026-07-20 10:00:00", "e1"))
    e2, _ = service.capture(_capture("2026-07-20 10:45:00", "e2"))
    e3, _ = service.capture(_capture("2026-07-20 10:46:00", "e3", direction="SHORT", entry_low=100, entry_high=101, invalidation=102, tp1=98, tp2=96))
    assert len({e1, e2, e3}) == 3
