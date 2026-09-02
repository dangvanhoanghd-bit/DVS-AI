from types import SimpleNamespace

from dvs_ai.domain.models import EntryStatus
from dvs_ai.services.paper_trade_service import PaperTradeService


class DummyProvider:
    exchange = SimpleNamespace(fetch_ohlcv=lambda *args, **kwargs: [])


class DummyDecision:
    @staticmethod
    def _trade_plan(direction, price, r15):
        return SimpleNamespace(
            entry_low=99.0,
            entry_high=100.0,
            invalidation=97.0,
            tp1=103.0,
            tp2=105.0,
            rr_to_tp2=2.0,
        )


def _analysis():
    r15 = SimpleNamespace(
        spring=False,
        upthrust=False,
    )
    return SimpleNamespace(
        symbol="TEST/USDT:USDT",
        direction="LONG",
        entry_status=EntryStatus.SETUP,
        action="LONG SETUP",
        confidence_score=57.0,
        long_entry_score=59.0,
        short_entry_score=10.0,
        risk=SimpleNamespace(risk_score=45.0),
        trade_plan=SimpleNamespace(rr_to_tp2=2.0),
        snapshot=SimpleNamespace(
            last_price=100.0,
            funding_pct=0.0,
        ),
        timeframes={"15m": r15},
        smart_entry=SimpleNamespace(
            smart_money_probability=55.0,
            explanation=(),
            fake_breakdown_score=0.0,
            fake_breakout_score=0.0,
            absorption_score=0.0,
            weak_hand_score=0.0,
            cmf_rsi_divergence="NONE",
        ),
        structure=SimpleNamespace(
            wyckoff_score=40.0,
            liquidity_score=30.0,
        ),
        regime=SimpleNamespace(regime="RANGE"),
        phase_summary="Accumulation",
        oi_state="Neutral",
        generated_at="2026-07-14 01:00:00",
        opportunity_rank=1,
        opportunity_score=60.0,
        opportunity_gate="RANKED",
        maturity_gate="CONFIRMED",
        trend_lifecycle="FIRST_RETEST",
        direction_confirmation_gate="CONFIRMED",
        footprint_gate="READY_CANDIDATE",
        microstructure=None,
    )


def _config():
    return SimpleNamespace(
        main_long_limit=25,
        main_short_limit=25,
        shadow_long_limit=50,
        shadow_short_limit=50,
        main_confidence=70,
        main_entry=65,
        main_risk_max=50,
        main_rr_min=1.8,
        shadow_confidence=55,
        shadow_entry=50,
        shadow_risk_max=60,
        shadow_rr_min=1.5,
        opportunity_main_top_n=3,
        opportunity_shadow_top_n=12,
        opportunity_min_score=52.0,
        shadow_opportunity_min_score=28.0,
        shadow_allow_wait_discovery=True,
        shadow_research_confidence=34.0,
        shadow_research_entry=35.0,
        shadow_fatal_micro_only=True,
        microstructure_min_cos=48.0,
        microstructure_shadow_min_absorption=18.0,
        microstructure_shadow_min_ofi_edge=6.0,
        microstructure_shadow_min_building=15.0,
    )


def test_shadow_setup_creates_pending_trade(tmp_path):
    service = PaperTradeService(
        DummyProvider(),
        DummyDecision(),
        str(tmp_path / "paper.db"),
        config=_config(),
    )

    ok, message = service.auto_consider(_analysis())
    assert ok is True
    assert "SHADOW" in message

    with service._connect() as con:
        trade = con.execute(
            "SELECT lab,status,direction FROM paper_trades"
        ).fetchone()
        evaluations = con.execute(
            "SELECT lab,eligible FROM signal_evaluations "
            "ORDER BY id"
        ).fetchall()

    assert trade == ("SHADOW", "PENDING", "LONG")
    assert evaluations == [("MAIN", 0), ("SHADOW", 1)]


def test_signal_evaluation_insert_keeps_lab(tmp_path):
    service = PaperTradeService(
        DummyProvider(),
        DummyDecision(),
        str(tmp_path / "paper.db"),
        config=_config(),
    )
    analysis = _analysis()
    eligible, reasons = service.eligibility(
        analysis, "LONG", "SHADOW"
    )
    service._record_evaluation(
        analysis,
        "LONG",
        eligible,
        reasons,
        source="AUTO",
        lab="SHADOW",
    )
    with service._connect() as con:
        row = con.execute(
            "SELECT source,lab,eligible FROM signal_evaluations"
        ).fetchone()
    assert row == ("AUTO", "SHADOW", 1)
