from types import SimpleNamespace

import pandas as pd

from dvs_ai.domain.models import (
    AlignmentAnalysis,
    MarketSnapshot,
    RegimeAnalysis,
    StructureAnalysis,
    TimeframeAnalysis,
)
from dvs_ai.engines.smart_entry_engine import SmartEntryEngine
from dvs_ai.services.paper_trade_service import PaperTradeService


def _tf(*, spring=False, upthrust=False, closes=None, rsi_values=None):
    closes = closes or tuple([100.0] * 80)
    rsi_values = rsi_values or tuple([50.0] * 80)
    return TimeframeAnalysis(
        timeframe="15m",
        close=closes[-1],
        price_change_pct=0.0,
        cmf=0.1,
        rsi=rsi_values[-1],
        ema20=100.0,
        ema50=99.0,
        ema200=95.0,
        adx=25.0,
        atr=1.0,
        relative_volume=0.55,
        support=95.0,
        resistance=105.0,
        spring=spring,
        upthrust=upthrust,
        market_phase="Accumulation",
        long_trend_score=60.0,
        short_trend_score=30.0,
        long_entry_score=60.0,
        short_entry_score=20.0,
        opens=closes,
        highs=tuple(x + 0.3 for x in closes),
        lows=tuple(x - 0.3 for x in closes),
        closes=closes,
        cmf_values=tuple(
            [0.05] * 76 + [0.04, 0.06, 0.08, 0.10]
        ),
        rsi_values=rsi_values,
    )


def test_smart_entry_uses_indicator_series_and_calls_retest():
    closes = tuple([100.0] * 74 + [102, 103, 104, 106, 105, 105.1])
    rsi_values = tuple([50.0] * 76 + [70.0, 62.0, 55.0, 48.0])
    rows = []
    for c in closes:
        rows.append({
            "open": c - 0.1,
            "high": c + 0.2,
            "low": c - 0.2,
            "close": c,
            "volume": 50.0,
        })
    frame = pd.DataFrame(rows)
    frame.loc[
        frame.index[-1],
        ["low", "close", "high"],
    ] = [100.15, 100.35, 100.5]

    r15 = _tf(
        closes=tuple(frame["close"]),
        rsi_values=rsi_values,
    )
    snap = MarketSnapshot(
        "X/USDT", 100.35, 100.35, 0, 1_000_000, 0,
        1000, 0, 0,
    )
    structure = StructureAnalysis(
        110, 90, 115, 85, 120, 80,
        "Không có sự kiện",
        "Không có tín hiệu",
        "Cân bằng",
        20, 20, (),
    )
    alignment = AlignmentAnalysis(
        "MÂU THUẪN", 50, 50, (), (), ""
    )
    regime = RegimeAnalysis(
        "RANGE", "NEUTRAL", 30, "THẤP", ""
    )

    result = SmartEntryEngine().analyze(
        {"15m": frame},
        {"15m": r15},
        snap,
        structure,
        alignment,
        regime,
    )
    assert any(
        "Long Retest" in line
        for line in result.explanation
    )
    # Chính chuỗi RSI supplied có rơi 22 điểm trong 4 mẫu.
    assert result.weak_hand_score >= 24


class CandleProvider:
    def __init__(self, candles):
        self.exchange = SimpleNamespace(
            fetch_ohlcv=lambda *args, **kwargs: candles
        )


class DummyDecision:
    pass


def test_partial_tp1_then_stop_accounts_realized_profit(tmp_path):
    candles = [
        [1_700_000_000_000, 100, 101.6, 100.0, 101.2, 10],
        [1_700_000_060_000, 101.2, 101.3, 98.9, 99.0, 10],
    ]
    service = PaperTradeService(
        CandleProvider(candles),
        DummyDecision(),
        str(tmp_path / "paper.db"),
    )
    with service._connect() as con:
        con.execute("""
            INSERT INTO paper_trades (
                pilot_id,created_at,signal_time,symbol,direction,source,status,
                entry_low,entry_high,planned_entry,fill_price,fill_time,
                invalidation,tp1,tp2,rr_planned,confidence,entry_score,
                risk_score,smart_money_score,wyckoff_score,regime,phase,
                oi_state,funding
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            service.PILOT_ID,
            "2023-11-14 00:00:00",
            "2023-11-14 00:00:00",
            "X/USDT",
            "LONG",
            "AUTO",
            "ACTIVE",
            100,
            100,
            100,
            100,
            "2023-11-14 00:00:00",
            99,
            101.5,
            102.3,
            2.3,
            80,
            80,
            20,
            70,
            70,
            "TREND",
            "Accumulation",
            "Neutral",
            0,
        ))
        trade_id = con.execute(
            "SELECT id FROM paper_trades"
        ).fetchone()[0]

    row = (
        trade_id,
        "2023-11-14 00:00:00",
        "X/USDT",
        "LONG",
        "ACTIVE",
        100,
        100,
        100,
        100,
        "2023-11-14 00:00:00",
        99,
        101.5,
        102.3,
        0.0,
        None,
    )
    service._update_one(row)

    with service._connect() as con:
        result, r_value, realized = con.execute(
            "SELECT result,r_multiple,tp1_realized_r "
            "FROM paper_trades WHERE id=?",
            (trade_id,),
        ).fetchone()

    assert result == "PARTIAL_STOP"
    assert round(r_value, 2) == 0.25
    assert round(realized, 2) == 0.75


def test_statistics_uses_r_multiple(tmp_path):
    service = PaperTradeService(
        CandleProvider([]),
        DummyDecision(),
        str(tmp_path / "paper.db"),
    )
    base = (
        service.PILOT_ID,
        "2023-11-14 00:00:00",
        "2023-11-14 00:00:00",
        "X/USDT",
        "LONG",
        "AUTO",
        "CLOSED",
        100,
        100,
        100,
        100,
        "2023-11-14 00:00:00",
        99,
        101.5,
        102.3,
        2.3,
        80,
        80,
        20,
        70,
        70,
        "TREND",
        "Accumulation",
        "Neutral",
        0,
    )
    with service._connect() as con:
        for result, r_value in [
            ("PARTIAL_STOP", 0.25),
            ("STOP", -1.0),
        ]:
            con.execute("""
                INSERT INTO paper_trades (
                    pilot_id,created_at,signal_time,symbol,direction,source,status,
                    entry_low,entry_high,planned_entry,fill_price,fill_time,
                    invalidation,tp1,tp2,rr_planned,confidence,entry_score,
                    risk_score,smart_money_score,wyckoff_score,regime,phase,
                    oi_state,funding,result,r_multiple
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, base + (result, r_value))

    stats = service.statistics()
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert stats["win_rate"] == 50.0
