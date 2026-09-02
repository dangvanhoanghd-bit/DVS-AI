from types import SimpleNamespace
import sys
import types
import pandas as pd

sys.modules.setdefault("pandas_ta", types.SimpleNamespace())
from dvs_ai.engines.indicator_engine import IndicatorEngine
from dvs_ai.engines.risk_engine import RiskEngine
from dvs_ai.domain.models import (
    AlignmentAnalysis, MarketSnapshot, RegimeAnalysis, TimeframeAnalysis,
    TradePlan
)


def _frame_for_silent_spring():
    rows = []
    for i in range(45):
        rows.append({
            "open": 100.2, "high": 100.8, "low": 99.8,
            "close": 100.1, "volume": 100.0,
        })
    # prior 20-bar support becomes 99.8; current sweeps with low volume.
    rows[-1] = {
        "open": 99.9, "high": 100.4, "low": 99.2,
        "close": 100.0, "volume": 60.0,
    }
    return pd.DataFrame(rows)


def test_silent_spring_is_detected():
    df = _frame_for_silent_spring()
    cmf = pd.Series([0.05] * len(df))
    spring_type, upthrust_type = IndicatorEngine._spring_variants(
        df, 99.8, 100.8, 0.60, cmf
    )
    assert spring_type == "SILENT"
    assert upthrust_type == "NONE"


def _tf():
    return TimeframeAnalysis(
        timeframe="15m", close=100, price_change_pct=0,
        cmf=0, rsi=50, ema20=100, ema50=99, ema200=95,
        adx=25, atr=1, relative_volume=1,
        support=95, resistance=105, spring=False, upthrust=False,
        market_phase="Transition", long_trend_score=50,
        short_trend_score=50, long_entry_score=50,
        short_entry_score=50, opens=(), highs=(), lows=(),
        closes=(), cmf_values=(), rsi_values=(),
    )


def test_liquidation_unsafe_is_detected():
    cfg = SimpleNamespace(
        leverage=50.0,
        maintenance_margin_rate=0.005,
        taker_fee_rate=0.0005,
        liquidation_buffer_pct=0.003,
        account_equity_usdt=1000.0,
        risk_per_trade_pct=1.0,
    )
    plan = TradePlan(
        "LONG", 99, 100, 95, 106, 110, 2.3, (), ()
    )
    snap = MarketSnapshot("X", 100, 100, 0, 1e6, 0, 1000, 0, 0)
    alignment = AlignmentAnalysis("ĐỒNG PHA LONG", 80, 20, (), (), "")
    regime = RegimeAnalysis("TREND", "LONG", 70, "VỪA", "")
    result = RiskEngine(cfg).analyze(
        snap, {"15m": _tf()}, alignment, regime, "LONG", plan
    )
    assert result.liquidation_safe is False
    assert result.max_safe_leverage < result.leverage
    assert any("thanh lý" in x.lower() for x in result.warnings)


def test_low_leverage_is_safe():
    cfg = SimpleNamespace(
        leverage=3.0,
        maintenance_margin_rate=0.005,
        taker_fee_rate=0.0005,
        liquidation_buffer_pct=0.003,
        account_equity_usdt=1000.0,
        risk_per_trade_pct=1.0,
    )
    plan = TradePlan(
        "LONG", 99, 100, 95, 106, 110, 2.3, (), ()
    )
    snap = MarketSnapshot("X", 100, 100, 0, 1e6, 0, 1000, 0, 0)
    alignment = AlignmentAnalysis("ĐỒNG PHA LONG", 80, 20, (), (), "")
    regime = RegimeAnalysis("TREND", "LONG", 70, "VỪA", "")
    result = RiskEngine(cfg).analyze(
        snap, {"15m": _tf()}, alignment, regime, "LONG", plan
    )
    assert result.liquidation_safe is True
    assert result.position_notional > 0
    assert result.margin_required > 0
