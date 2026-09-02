from types import ModuleType, SimpleNamespace
from pathlib import Path
import json
import sys

ccxt_stub = ModuleType("ccxt")
ccxt_stub.binance = lambda *args, **kwargs: None
sys.modules.setdefault("ccxt", ccxt_stub)
sys.modules.setdefault("pandas_ta", ModuleType("pandas_ta"))

from dvs_ai.domain.models import EntryStatus, MarketBrief
from dvs_ai.services.scanner import ScannerService


def fake_analysis(
    symbol,
    confidence=60.0,
    entry=65.0,
    trend=75.0,
    direction_confirmation=80.0,
    risk=20.0,
    status=EntryStatus.SETUP,
):
    return SimpleNamespace(
        symbol=symbol,
        direction="LONG",
        confidence_score=confidence,
        confidence_before_context=0.0,
        confidence_context_adjustment=0.0,
        entry_status=status,
        long_entry_score=entry,
        short_entry_score=10.0,
        long_trend_score=trend,
        short_trend_score=10.0,
        direction_confirmation_score=direction_confirmation,
        direction_confirmation_gate="CONFIRMED",
        market_bias_gate="PASS",
        market_bias_code="STRONG_LONG",
        trend_lifecycle="EARLY_FORMATION",
        maturity_gate="EARLY_FORMATION",
        risk=SimpleNamespace(risk_score=risk, liquidation_safe=True),
        smart_entry=SimpleNamespace(smart_money_probability=70.0),
        trade_plan=SimpleNamespace(rr_to_tp2=2.0),
        reasons=(),
        opportunity_score=0.0,
        opportunity_rank=999,
        opportunity_gate="UNRANKED",
    )


def fake_replace(obj, **changes):
    data = dict(obj.__dict__)
    data.update(changes)
    return SimpleNamespace(**data)


def test_calibration_bounded(monkeypatch):
    import dvs_ai.services.scanner as module
    monkeypatch.setattr(module, "replace", fake_replace)
    a = fake_analysis("A", confidence=60.0)
    brief = MarketBrief(
        "LONG", 75, "LONG", "LOW", "", "STRONG_LONG", 75
    )
    out = ScannerService.calibrate_context_confidence(
        a, brief, max_boost=5.0
    )
    assert 60.0 <= out.confidence_score <= 65.0


def test_calibration_does_not_override_wait(monkeypatch):
    import dvs_ai.services.scanner as module
    monkeypatch.setattr(module, "replace", fake_replace)
    a = fake_analysis("A", confidence=48.0, status=EntryStatus.WAIT)
    brief = MarketBrief(
        "LONG", 75, "LONG", "LOW", "", "STRONG_LONG", 75
    )
    out = ScannerService.calibrate_context_confidence(
        a, brief, max_boost=5.0
    )
    assert out.confidence_score == 48.0
    assert out.confidence_context_adjustment == 0.0


def test_ranking_strongest_first(monkeypatch):
    import dvs_ai.services.scanner as module
    monkeypatch.setattr(module, "replace", fake_replace)
    results = {
        "A": fake_analysis("A", confidence=72, entry=75, trend=82),
        "B": fake_analysis("B", confidence=62, entry=60, trend=70),
        "C": fake_analysis(
            "C",
            confidence=35,
            entry=25,
            trend=30,
            risk=90,
            status=EntryStatus.WAIT,
        ),
    }
    ranked = ScannerService.rank_opportunities(
        results, minimum_score=52.0
    )
    assert ranked["A"].opportunity_rank == 1
    assert ranked["A"].opportunity_score > ranked["B"].opportunity_score
    assert ranked["C"].opportunity_gate == "LOW_QUALITY"


def test_config_limits():
    root = Path(__file__).parents[1]
    cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
    assert cfg["opportunity_main_top_n"] == 3
    assert cfg["opportunity_shadow_top_n"] == 12
    assert cfg["opportunity_min_score"] == 52.0
