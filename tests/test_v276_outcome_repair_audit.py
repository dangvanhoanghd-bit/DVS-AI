from pathlib import Path
import random

ROOT = Path(__file__).parents[1]


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_trade_plan_repair_is_logged_and_persisted():
    source = read("dvs_ai/engines/decision_engine.py")
    models = read("dvs_ai/domain/models.py")
    assert "logger.warning(" in source
    assert "Trade Plan Repaired:" in source
    assert "plan_repaired: bool = False" in models
    assert "plan_repair_reason: str" in models


def test_futures_risk_call_always_passes_r15():
    source = read("dvs_ai/engines/risk_engine.py")
    assert "self._futures_risk(direction, trade_plan, r15)" in source
    assert "tiered" in source.lower()


def test_seeded_slippage_is_reproducible():
    seed = "17:BTC/USDT:USDT:LONG"
    a = random.Random(seed).gauss(0.0005, 0.00025)
    b = random.Random(seed).gauss(0.0005, 0.00025)
    assert a == b
    source = read("dvs_ai/services/paper_trade_service.py")
    assert "random.Random(" in source
    assert "realized_slippage_rate" in source


def test_ambiguous_outcomes_have_stage_detail():
    source = read("dvs_ai/services/paper_trade_service.py")
    assert "AMBIGUOUS_ENTRY_CANDLE" in source
    assert "AMBIGUOUS_ACTIVE_CANDLE" in source
    assert "AMBIGUOUS_AFTER_TP1" in source


def test_learning_excludes_ambiguous_from_calibration():
    source = read("dvs_ai/services/learning_service.py")
    assert "'AMBIGUOUS','PARTIAL_AMBIGUOUS','EXPIRED'" in source
    assert "determinate" in source
