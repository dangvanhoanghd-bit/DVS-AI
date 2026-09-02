from types import SimpleNamespace
from pathlib import Path

from dvs_ai.domain.models import EntryStatus
from dvs_ai.engines.decision_engine import DecisionEngine


def tf(cmf15=0.1, cmf1=0.1, close=101, ema20=100, rsi=60):
    return {
        "15m": SimpleNamespace(
            cmf=cmf15,
            close=close,
            ema20=ema20,
            rsi=rsi,
        ),
        "1h": SimpleNamespace(cmf=cmf1),
    }


def structure(signal="NONE", event="NONE", test="NONE"):
    return SimpleNamespace(
        wyckoff_signal=signal,
        liquidity_event=event,
        wyckoff_test=test,
    )


def context(direction="LONG"):
    return (
        SimpleNamespace(direction=direction),
        SimpleNamespace(label=f"ĐỒNG PHA {direction}"),
        SimpleNamespace(
            long_opportunity_index=70 if direction == "LONG" else 10,
            short_opportunity_index=70 if direction == "SHORT" else 10,
        ),
    )


def test_upthrust_alone_cannot_confirm_short_with_positive_cmf():
    regime, alignment, smart = context("SHORT")
    score, gate, reasons = DecisionEngine._direction_confirmation(
        "SHORT",
        tf(cmf15=0.16, cmf1=0.10, close=101, ema20=100, rsi=59),
        structure(signal="Upthrust"),
        regime,
        alignment,
        smart,
    )
    assert gate != "CONFIRMED"
    assert score < 72
    assert any("Phạt SHORT" in item for item in reasons)


def test_short_confirms_after_breakdown_and_negative_money_flow():
    regime, alignment, smart = context("SHORT")
    score, gate, _ = DecisionEngine._direction_confirmation(
        "SHORT",
        tf(cmf15=-0.15, cmf1=-0.08, close=98, ema20=100, rsi=43),
        structure(
            signal="Upthrust",
            event="breakdown xác nhận",
            test="TEST AFTER UPTHRUST",
        ),
        regime,
        alignment,
        smart,
    )
    assert gate == "CONFIRMED"
    assert score >= 72


def test_csv_contains_decision_snapshot_fields():
    source = (
        Path(__file__).parents[1] / "dvs_ai/ui/main_window.py"
    ).read_text(encoding="utf-8")
    for field in (
        "maturity_score",
        "direction_confirmation_score",
        "market_bias_code",
        "smart_money_probability",
        "risk_score",
    ):
        assert f'"{field}"' in source
