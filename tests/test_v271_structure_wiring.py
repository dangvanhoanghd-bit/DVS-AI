from pathlib import Path

ROOT = Path(__file__).parents[1]


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_decision_exposes_structure_evidence():
    source = read("dvs_ai/engines/decision_engine.py")
    assert "Sweep Volume State:" in source
    assert "Structure Wyckoff Test:" in source


def test_smart_entry_does_not_double_score_structure():
    source = read("dvs_ai/engines/smart_entry_engine.py")
    assert "diagnostic only, not scored twice" in source


def test_paper_trade_keeps_structure_tags_safely():
    source = read("dvs_ai/services/paper_trade_service.py")
    assert 'getattr(a.structure, "sweep_volume_state", "NONE")' in source
    assert "STRUCT_TEST_AFTER_SPRING" in source
    assert "STRUCT_TEST_AFTER_UPTHRUST" in source


def test_ui_displays_structure_evidence():
    source = read("dvs_ai/ui/main_window.py")
    assert "Sweep Volume State:" in source
    assert "Structure Test:" in source
    assert "Sweep chưa được volume xác nhận" in source
