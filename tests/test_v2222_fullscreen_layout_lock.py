from pathlib import Path


def ui_source():
    return Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")


def test_no_scan_time_splitter_geometry_mutation():
    source = ui_source()
    assert "splitter.setSizes(" not in source
    assert "detail_splitter.setSizes" not in source
    assert "_scan_splitter_sizes" not in source


def test_detail_page_uses_stable_scroll_viewport():
    source = ui_source()
    assert "detail_scroll = QScrollArea()" in source
    assert "ScrollBarAlwaysOn" in source
    assert "detail_content.setMinimumHeight(790)" in source


def test_vertical_sections_have_deterministic_heights():
    source = ui_source()
    assert "self.market_chart.setFixedHeight(350)" in source
    assert "self.tf_table.setFixedHeight(130)" in source
    assert "self.story_container.setFixedHeight(122)" in source
    assert "plan_box.setFixedHeight(68)" in source


def test_market_chart_has_no_conflicting_minimum():
    source = Path("dvs_ai/ui/market_chart.py").read_text(encoding="utf-8")
    assert "self.setMinimumHeight(430)" not in source
    assert "self.setMinimumHeight(0)" in source


def test_execution_safety_unchanged():
    import json
    raw = json.loads(Path("config.json").read_text(encoding="utf-8"))
    assert raw["execution_mode"] == "PAPER"
    assert raw["execution_live_enabled"] is False
