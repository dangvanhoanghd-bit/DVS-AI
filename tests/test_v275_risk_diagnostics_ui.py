from pathlib import Path

ROOT = Path(__file__).parents[1]


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_detail_panel_shows_all_risk_diagnostics():
    source = read("dvs_ai/ui/main_window.py")
    assert "Dynamic Buffer:" in source
    assert "Effective Stop:" in source
    assert "Leverage Constraint:" in source


def test_risk_view_shows_constraint_state():
    source = read("dvs_ai/ui/main_window.py")
    assert "Leverage constraint:" in source
    assert "dynamic_buffer_used" in source
    assert "effective_stop_distance" in source
    assert "leverage_constraint_state" in source


def test_decision_reasons_use_separate_lines():
    source = read("dvs_ai/engines/decision_engine.py")
    assert "Effective Stop:" in source
    assert "Leverage Constraint:" in source


def test_tooltip_explains_new_fields():
    source = read("dvs_ai/ui/main_window.py")
    assert "Dynamic Buffer là khoảng đệm thanh lý theo ATR" in source
    assert "Effective Stop đã gồm phí/trượt giá" in source
