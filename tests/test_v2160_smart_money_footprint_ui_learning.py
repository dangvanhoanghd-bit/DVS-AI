from pathlib import Path


def test_version_matches_app_version():
    from dvs_ai import __version__
    from dvs_ai.version import APP_VERSION
    assert __version__ == APP_VERSION

def test_smart_money_tab_exposes_footprint_fields():
    source = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    for token in (
        "FP Raw",
        "FP Context",
        "Confirm",
        "Align",
        "FP Gate",
        "Position",
        "Regime",
    ):
        assert token in source


def test_learning_has_footprint_lifecycle_matrix():
    source = Path("dvs_ai/services/learning_service.py").read_text(
        encoding="utf-8"
    )
    assert "def footprint_lifecycle_matrix" in source
    assert "confirmation_depth" in source
    assert "alignment" in source


def test_paper_trade_stores_gate_and_position_regime():
    source = Path("dvs_ai/services/paper_trade_service.py").read_text(
        encoding="utf-8"
    )
    assert "FOOTPRINT_GATE_" in source
    assert "POSITION_REGIME_" in source


def test_auto_paper_remains_disabled():
    import json

    raw = json.loads(Path("config.json").read_text(encoding="utf-8"))
    assert raw.get("auto_paper_execution_enabled", False) is False
    assert raw.get("execution_live_enabled", False) is False
