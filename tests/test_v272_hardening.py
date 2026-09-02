from pathlib import Path
from types import SimpleNamespace

from dvs_ai.engines.retest_rules import assess_retest
from dvs_ai.engines.risk_engine import RiskEngine
from dvs_ai.domain.models import (
    TimeframeAnalysis, TradePlan, MarketSnapshot,
    AlignmentAnalysis, RegimeAnalysis,
)


def test_retest_compares_event_volume_and_spread():
    result = assess_retest(
        direction="LONG", close=101, high=101.3, low=100.05,
        level=100, atr=1, relative_volume=0.55,
        breakout_close=101, current_volume=50, event_volume=100,
        current_spread=1.25, event_spread=2.0,
    )
    assert result.confirmed is True
    assert result.score == 20.0


def test_retest_without_breakout_is_zero():
    result = assess_retest(
        direction="LONG", close=100.1, high=100.2, low=99.9,
        level=100, atr=1, relative_volume=0.5,
        breakout_close=100.01,
    )
    assert result.confirmed is False
    assert result.score == 0.0


def _tf():
    return TimeframeAnalysis(
        timeframe="15m", close=100, price_change_pct=0,
        cmf=0, rsi=50, ema20=100, ema50=99, ema200=95,
        adx=25, atr=2, relative_volume=1,
        support=95, resistance=105, spring=False, upthrust=False,
        market_phase="Transition", long_trend_score=50,
        short_trend_score=50, long_entry_score=50,
        short_entry_score=50, opens=(), highs=(), lows=(),
        closes=(), cmf_values=(), rsi_values=(),
    )


def test_risk_dynamic_buffer_and_exposure_cap():
    cfg = SimpleNamespace(
        leverage=5, maintenance_margin_rate=.005,
        taker_fee_rate=.0005, liquidation_buffer_pct=.003,
        account_equity_usdt=1000, risk_per_trade_pct=1,
        max_exposure_multiple=4, paper_slippage_rate=.0005,
    )
    plan = TradePlan("LONG", 99, 100, 95, 104, 108, 2, (), ())
    snap = MarketSnapshot("X",100,100,0,1e6,0,1000,0,0)
    align = AlignmentAnalysis("ĐỒNG PHA LONG",80,20,(),(),"")
    regime = RegimeAnalysis("TREND","LONG",70,"VỪA","")
    result = RiskEngine(cfg).analyze(
        snap, {"15m": _tf()}, align, regime, "LONG", plan
    )
    assert result.dynamic_buffer_used >= .003
    assert result.position_notional <= 4000
    assert result.effective_stop_distance > 4.5


def test_source_contains_strict_retest_window():
    source = (
        Path(__file__).parents[1]
        / "dvs_ai/engines/smart_entry_engine.py"
    ).read_text(encoding="utf-8")
    assert "breakout_window = d15.iloc[-8:-2]" in source
    assert "long_retest.score * 3.5" in source
