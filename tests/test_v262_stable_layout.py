from pathlib import Path


def _source():
    path = (
        Path(__file__).parents[1]
        / "dvs_ai" / "ui" / "main_window.py"
    )
    return path.read_text(encoding="utf-8")


def test_scan_preserves_user_view():
    source = _source()
    assert "self._scan_view_tab = self.tabs.currentIndex()" in source
    assert "self.table.blockSignals(True)" in source
    assert "preserve_timeframe=True" in source
    assert "self._scan_outer_scroll" in source
    assert "self._schedule_detail_state_restore()" in source


def test_universe_scan_updates_in_place():
    source = _source()
    assert "if clear and not self.config.universe_enabled:" in source
    assert "Round-robin universe: update in place" in source


def test_story_panels_cannot_collapse():
    source = _source()
    assert "self.story_container.setFixedHeight(122)" in source
    assert "self.timeline_text.setMinimumHeight(" in source
    assert "self.market_story.setMinimumHeight(" in source
