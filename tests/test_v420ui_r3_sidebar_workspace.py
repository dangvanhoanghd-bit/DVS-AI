from pathlib import Path


def _source() -> str:
    return Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')


def test_sidebar_workspace_replaces_primary_tab_bar_navigation():
    text = _source()
    assert 'self.sidebar = QTreeWidget' in text
    assert 'self.workspace_splitter = QSplitter' in text
    assert 'self.tabs.tabBar().hide()' in text
    assert 'self._build_sidebar_navigation()' in text


def test_sidebar_preserves_priority_and_complete_group_tree():
    text = _source()
    method = text[text.index('def _build_sidebar_navigation'):text.index('def _on_sidebar_item_clicked')]
    labels = [
        '"Dashboard"',
        '"Phân tích chi tiết"',
        '"Giao dịch"',
        '"Phân tích thị trường"',
        '"Giám sát"',
        '"Nghiên cứu"',
        '"Công cụ"',
    ]
    positions = [method.index(label) for label in labels]
    assert positions == sorted(positions)
    for child in (
        '"Decision Core"', '"Smart Entry"', '"Paper Trade"',
        '"Integrity Operations"', '"Episode Audit"',
        '"Thí nghiệm"', '"So sánh & tái lập"', '"Cohort & Batch"',
        '"Trung tâm lỗi"',
    ):
        assert child in method


def test_sidebar_child_selection_switches_primary_and_nested_workspace():
    text = _source()
    method = text[text.index('def _on_sidebar_item_clicked'):text.index('def _make_folder_tabs')]
    assert 'self.tabs.setCurrentIndex(primary_index)' in method
    assert 'nested_tabs.setCurrentIndex(child_index)' in method
    assert 'self.trading_folder_widget: self.trading_tabs' in method
    assert 'self.monitoring_folder_widget: self.monitoring_tabs' in method
    assert 'self.research_folder_widget: self.research_tabs' in method


def test_nested_folder_tab_bars_are_hidden_but_page_registries_remain():
    text = _source()
    method = text[text.index('def _build_sidebar_navigation'):text.index('def _on_sidebar_item_clicked')]
    assert 'nested_tabs.tabBar().hide()' in method
    for registry in (
        'self.trading_tabs', 'self.market_analysis_tabs', 'self.monitoring_tabs',
        'self.research_tabs', 'self.tools_tabs',
    ):
        assert registry in method
