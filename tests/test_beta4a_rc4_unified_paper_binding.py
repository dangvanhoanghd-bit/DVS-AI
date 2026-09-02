from types import SimpleNamespace

from dvs_ai.domain.models import EntryStatus, TradePlan
from dvs_ai.services.live_episode_capture import LiveEpisodeCapture
from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore
from dvs_ai.services.paper_trade_service import PaperTradeService


class Config:
    refresh_seconds = 60


class Decision:
    WEIGHTS = {"15m": .40, "1h": .35, "4h": .17, "1d": .08}


class DummyProvider:
    exchange = None


def analysis(ts="2026-07-20 10:00:00"):
    return SimpleNamespace(
        symbol="BTC/USDT:USDT", direction="LONG", generated_at=ts,
        long_entry_score=60.0, short_entry_score=20.0,
        long_trend_score=70.0, short_trend_score=15.0,
        confidence_score=58.0, opportunity_score=62.0,
        entry_status=EntryStatus.SETUP, trend_lifecycle="FIRST_RETEST",
        decision_hard_reasons=(), reasoning_hard_blocks=(),
        direction_confirmation_gate="CONFIRMED", direction_confirmation_score=75.0,
        microstructure_gate="PASS", opportunity_gate="SHADOW_ELIGIBLE", market_bias_gate="PASS",
        phase_summary="Accumulation / Markup",
        regime=SimpleNamespace(regime="TREND"),
        risk=SimpleNamespace(risk_score=28.0, risk_level="LOW"),
        smart_entry=SimpleNamespace(smart_money_probability=66.0, state="WATCH"),
        timeframes={"15m": SimpleNamespace(support=99.0, resistance=103.0, atr=2.0, spring=False, upthrust=False)},
        trade_plan=TradePlan(direction="LONG", entry_low=99.0, entry_high=100.0,
            invalidation=98.0, tp1=102.0, tp2=104.0, rr_to_tp2=3.0,
            confirmations=(), cancellation_rules=()),
    )


def test_capture_attaches_exact_candidate_outcome_identity(tmp_path):
    store = OutcomeInfrastructureStore(tmp_path / "paper.db")
    capture = LiveEpisodeCapture(store, Decision(), Config())
    item = analysis()
    identity = capture.capture_with_identity(item)
    assert identity.complete is True
    assert not hasattr(item, "_dvs_capture_complete")
    with store.connect() as con:
        row = con.execute(
            "select candidate_id from candidate_outcomes where outcome_id=?",
            (identity.outcome_id,),
        ).fetchone()
    assert row[0] == identity.candidate_id

def test_repeated_capture_returns_existing_candidate_identity(tmp_path):
    store = OutcomeInfrastructureStore(tmp_path / "paper.db")
    capture = LiveEpisodeCapture(store, Decision(), Config())
    first = analysis()
    second = analysis("2026-07-20 10:15:00")
    _, first_id = capture.capture(first)
    _, second_id = capture.capture(second)
    assert second_id is None  # legacy service contract remains unchanged
    identity = capture.capture_with_identity(second)
    assert identity.candidate_id == first_id
    assert identity.outcome_id


def test_paper_lifecycle_projects_to_unified_atomically(tmp_path):
    db = tmp_path / "paper.db"
    store = OutcomeInfrastructureStore(db)
    capture = LiveEpisodeCapture(store, Decision(), Config())
    item = analysis()
    identity = capture.capture_with_identity(item)
    candidate_id = identity.candidate_id
    service = PaperTradeService(DummyProvider(), Decision(), str(db), config=SimpleNamespace())

    with service._connect() as con:
        service._sync_unified_lifecycle(
            con, trade_id=7, candidate_id=candidate_id, outcome_id=identity.outcome_id,
            current_status="ACTIVE", result=None, event_time="2026-07-20 10:01:00",
            fill_time="2026-07-20 10:01:00", fill_price=99.5, close_price=None,
            realized_r=0.0, mfe_r=0.2, mae_r=0.1, detail="ACTIVE",
        )
    with store.connect() as con:
        assert con.execute("select status from decision_candidates where candidate_id=?", (candidate_id,)).fetchone()[0] == "ACTIVE"
        assert con.execute("select status from candidate_outcomes where outcome_id=?", (identity.outcome_id,)).fetchone()[0] == "PENDING"

    with service._connect() as con:
        service._sync_unified_lifecycle(
            con, trade_id=7, candidate_id=candidate_id, outcome_id=identity.outcome_id,
            current_status="CLOSED", result="TP2", event_time="2026-07-20 10:10:00",
            fill_time="2026-07-20 10:01:00", fill_price=99.5, close_price=104.0,
            realized_r=2.2, mfe_r=2.4, mae_r=0.3, detail="TP2",
        )
    with store.connect() as con:
        assert con.execute("select status from decision_candidates where candidate_id=?", (candidate_id,)).fetchone()[0] == "WIN"
        outcome = con.execute("select status,realized_r from candidate_outcomes where outcome_id=?", (identity.outcome_id,)).fetchone()
        assert outcome[0] == "WIN"
        assert outcome[1] == 2.2
        assert con.execute("select count(*) from candidate_outcome_events where candidate_id=?", (candidate_id,)).fetchone()[0] >= 2


def test_auto_trade_fails_closed_without_unified_identity(tmp_path):
    service = PaperTradeService(DummyProvider(), Decision(), str(tmp_path / "paper.db"), config=SimpleNamespace())
    # Fail before any decision-engine/trade-plan access; this is the identity gate.
    ok, reason = service.create_trade(
        SimpleNamespace(), "LONG", source="AUTO_SHADOW", lab="SHADOW",
        require_unified_identity=True
    )
    assert ok is False
    assert reason == "UNIFIED_IDENTITY_NOT_READY"
