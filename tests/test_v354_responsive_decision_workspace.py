from pathlib import Path


def _source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "dvs_ai" / "ui" / "main_window.py").read_text(encoding="utf-8")


def test_decision_core_uses_separate_workspace_pages():
    source = _source()
    assert 'self.core_workspace_tabs = QTabWidget()' in source
    assert 'addTab(overview_scroll, "Tổng quan")' in source
    assert 'addTab(evidence_page, "Evidence")' in source
    assert 'addTab(conclusion_page, "Kết luận & giải thích")' in source


def test_overview_is_scrollable_and_evidence_is_resizable():
    source = _source()
    assert 'overview_scroll.setWidgetResizable(True)' in source
    assert 'self.qualification_evidence_splitter.setChildrenCollapsible(False)' in source
    assert 'self.qualification_evidence_table.setMinimumHeight(330)' in source
    assert 'self.qualification_evidence_detail.setMinimumHeight(330)' in source


def test_release_is_ui_only_and_keeps_existing_authority_language():
    source = _source()
    assert 'PAPER AUTHORITY: LEGACY' in source
    assert 'QUALIFICATION EVIDENCE CENTER · READ ONLY' in source
