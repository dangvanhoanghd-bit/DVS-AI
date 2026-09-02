from pathlib import Path


def _primary_build_block(source: str) -> str:
    return source[source.index('# 4.2.0-UI-r2'):source.index('self._apply_ux_mode()')]


def test_main_window_build_order_prioritizes_daily_operations():
    source = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    block = _primary_build_block(source)
    calls = [
        'self._build_dashboard()',
        'self._build_detail_tab()',
        'self._build_trading_folder_tab()',
        'self._build_market_analysis_folder_tab()',
        'self._build_monitoring_folder_tab()',
        'self._build_research_folder_tab()',
        'self._build_tools_folder_tab()',
    ]
    positions = [block.index(call) for call in calls]
    assert positions == sorted(positions)


def test_detail_is_second_and_grouped_folders_follow():
    source = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    block = _primary_build_block(source)
    assert block.index('self._build_dashboard()') < block.index('self._build_detail_tab()')
    assert block.index('self._build_detail_tab()') < block.index('self._build_trading_folder_tab()')
    assert block.index('self._build_monitoring_folder_tab()') < block.index('self._build_research_folder_tab()')
    assert block.index('self._build_research_folder_tab()') < block.index('self._build_tools_folder_tab()')


def test_research_modules_are_nested_under_one_parent_tab():
    source = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    assert 'self.tabs.addTab(folder, "Nghiên cứu")' in source
    assert 'self.research_tabs.addTab(' in source
    assert '"Thí nghiệm"' in source
    assert '"So sánh & tái lập"' in source
    assert '"Cohort & Batch"' in source
    assert 'self.tabs.addTab(self.research_experiment_widget' not in source
    assert 'self.tabs.addTab(self.research_comparison_widget' not in source
    assert 'self.tabs.addTab(self.research_cohort_widget' not in source


def test_tab_bars_are_stable_and_scrollable():
    source = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    assert 'self.tabs.setMovable(False)' in source
    assert 'self.tabs.setUsesScrollButtons(True)' in source
    assert 'self.research_tabs.setMovable(False)' in source
    assert 'self.research_tabs.setUsesScrollButtons(True)' in source
    assert 'tabs.setMovable(False)' in source
    assert 'tabs.setUsesScrollButtons(True)' in source
