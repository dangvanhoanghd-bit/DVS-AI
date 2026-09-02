from pathlib import Path


def test_launcher_has_no_unescaped_ampersand_in_title_or_banner():
    text = Path("START_DVS_AI.bat").read_text(encoding="utf-8")
    assert "Indicator Inspector & Confidence Breakdown" not in text
    assert "Performance and Stability" in text


def test_replay_is_lazy_loaded_from_workspace_change():
    text = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    assert "self._qualification_replay_pending_record = record" in text
    detail_block = text.split("def _show_qualification_evidence_detail", 1)[1].split("def _on_core_workspace_changed", 1)[0]
    assert "self._load_qualification_replay(record)" not in detail_block
    workspace_block = text.split("def _on_core_workspace_changed", 1)[1].split("def _load_qualification_replay", 1)[0]
    assert "self._load_qualification_replay(record)" in workspace_block


def test_scan_render_marks_evidence_dirty_instead_of_refreshing_table():
    text = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    block = text.split("def _render_shadow_qualification_dashboard", 1)[1].split("def _refresh_qualification_evidence", 1)[0]
    assert "self._qualification_evidence_dirty = True" in block
    assert "self._refresh_qualification_evidence()" not in block
