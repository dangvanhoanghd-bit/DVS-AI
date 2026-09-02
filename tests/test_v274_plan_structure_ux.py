from pathlib import Path


ROOT = Path(__file__).parents[1]


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_trade_plan_has_soft_repair_and_hard_failure():
    source = read("dvs_ai/engines/decision_engine.py")
    assert "Soft repair for small geometry violations" in source
    assert "minimum_gap = max(0.15 * atr" in source
    assert "Trade plan invariant failed after repair" in source


def test_decision_reasons_show_dynamic_risk_fields():
    source = read("dvs_ai/engines/decision_engine.py")
    assert "Dynamic Buffer:" in source
    assert "Effective Stop:" in source
    assert "Leverage Constraint:" in source


def test_structure_precomputes_rolling_levels():
    source = read("dvs_ai/engines/structure_engine.py")
    assert 'd15["low"].shift(1).rolling(20' in source
    assert 'd15["high"].shift(1).rolling(20' in source
    assert "baseline = d15.iloc" not in source


def test_ui_has_structure_test_tooltips():
    source = read("dvs_ai/ui/main_window.py")
    assert "Structure Test là phép xác nhận" in source
    assert "Sweep Volume State cho biết" in source


def test_risk_engine_receives_r15():
    source = read("dvs_ai/engines/risk_engine.py")
    assert "plan: TradePlan," in source
    assert "r15: TimeframeAnalysis," in source
    assert "self._futures_risk(direction, trade_plan, r15)" in source
