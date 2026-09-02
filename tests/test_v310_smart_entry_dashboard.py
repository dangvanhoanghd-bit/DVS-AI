from pathlib import Path

SOURCE = Path(__file__).parents[1] / "dvs_ai" / "ui" / "main_window.py"
VERSION = Path(__file__).parents[1] / "dvs_ai" / "version.py"


def test_smart_entry_dashboard_widgets_are_present():
    text = SOURCE.read_text(encoding="utf-8")
    for marker in (
        "SMART ENTRY DASHBOARD",
        "CHỈ SỐ CỐT LÕI",
        "XÁC SUẤT TƯƠNG ĐỐI",
        "TRIGGER MATRIX",
        "WYCKOFF / ENTRY TIMELINE",
        "smart_score_bar",
        "smart_probability",
        "smart_trigger_text",
    ):
        assert marker in text


def test_renderer_uses_engine_outputs_without_trading_side_effects():
    text = SOURCE.read_text(encoding="utf-8")
    assert "long_opportunity_index" in text
    assert "short_opportunity_index" in text
    assert "smart_money_probability" in text
    segment = text[text.index("def _render_smart_entry_for_analysis"):text.index("def _sync_views_to_selection")]
    assert "submit_order" not in segment
    assert "place_order" not in segment


def test_version_matches_app_version():
    from dvs_ai import __version__
    from dvs_ai.version import APP_VERSION
    assert __version__ == APP_VERSION

