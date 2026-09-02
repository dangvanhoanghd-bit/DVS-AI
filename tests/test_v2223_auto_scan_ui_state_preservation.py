from pathlib import Path


def source():
    return Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")


def finalization_commit_body():
    text = source()
    start = text.index("def _commit_finalization_payload")
    end = text.index("def _process_auto_paper_batch", start)
    return text[start:end]


def test_outer_scroll_is_captured():
    text = source()
    assert "self._scan_outer_scroll" in text
    assert "self.detail_scroll_area.verticalScrollBar().value()" in text


def test_selected_coin_refresh_happens_after_async_finalization():
    text = source()
    on_finished = text[text.index("def on_finished"):text.index("def _start_async_finalization")]
    commit = finalization_commit_body()
    assert "self._start_async_finalization()" in on_finished
    assert "finalized_results = dict(payload.get" in commit
    assert "self.results = finalized_results" in commit
    assert commit.count("self.show_selected(") >= 1


def test_restore_runs_after_three_qt_phases():
    text = source()
    assert "for delay in (0, 40, 140)" in text
    assert "self._schedule_detail_state_restore()" in text


def test_final_refresh_is_geometry_frozen():
    commit = finalization_commit_body()
    assert "with self.ui_geometry.freeze(detail_widget)" in commit
    assert "self.show_selected(" in commit


def test_auto_scan_button_width_is_bounded():
    text = source()
    assert "self.auto_scan_btn.setMinimumWidth(112)" in text
    assert "self.auto_scan_btn.setMaximumWidth(132)" in text


def test_execution_safety_unchanged():
    import json
    raw = json.loads(Path("config.json").read_text(encoding="utf-8"))
    assert raw["execution_mode"] == "PAPER"
    assert raw["execution_live_enabled"] is False
