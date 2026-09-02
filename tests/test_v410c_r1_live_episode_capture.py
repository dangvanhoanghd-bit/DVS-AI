from types import SimpleNamespace
from dvs_ai.domain.models import EntryStatus, TradePlan
from dvs_ai.services.live_episode_capture import LiveEpisodeCapture
from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore

class Config:
    refresh_seconds = 60

class Decision:
    WEIGHTS = {"15m": .40, "1h": .35, "4h": .17, "1d": .08}


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


def test_live_capture_creates_episode_candidate_and_trace(tmp_path):
    store = OutcomeInfrastructureStore(tmp_path / "paper.db")
    adapter = LiveEpisodeCapture(store, Decision(), Config())
    episode_id, candidate_id = adapter.capture(analysis())
    assert episode_id and candidate_id
    with store.connect() as con:
        assert con.execute("select count(*) from setup_episodes").fetchone()[0] == 1
        assert con.execute("select count(*) from decision_candidates").fetchone()[0] == 1
        trace = con.execute("select trace_json from decision_diagnostic_traces").fetchone()[0]
    assert '"smart_money_probability"' in trace
    assert '"risk_score"' in trace
    assert '"trend_directional"' in trace


def test_repeated_capture_groups_episode(tmp_path):
    store = OutcomeInfrastructureStore(tmp_path / "paper.db")
    adapter = LiveEpisodeCapture(store, Decision(), Config())
    adapter.capture(analysis())
    adapter.capture(analysis("2026-07-20 10:15:00"))
    with store.connect() as con:
        assert con.execute("select count(*) from setup_episodes").fetchone()[0] == 1
        assert con.execute("select count(*) from episode_evaluations").fetchone()[0] == 2
