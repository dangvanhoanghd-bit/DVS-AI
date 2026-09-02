from pathlib import Path


def test_primary_navigation_is_compact_and_prioritized():
    text = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    build_block = text[text.index('# 4.2.0-UI-r2'):text.index('self._apply_ux_mode()')]
    expected = [
        'self._build_dashboard()',
        'self._build_detail_tab()',
        'self._build_trading_folder_tab()',
        'self._build_market_analysis_folder_tab()',
        'self._build_monitoring_folder_tab()',
        'self._build_research_folder_tab()',
        'self._build_tools_folder_tab()',
    ]
    positions = [build_block.index(item) for item in expected]
    assert positions == sorted(positions)


def test_recent_modules_are_grouped_not_primary_tabs():
    text = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    build_block = text[text.index('# 4.2.0-UI-r2'):text.index('self._apply_ux_mode()')]
    for direct_builder in (
        '_build_statistical_diagnostics_tab()',
        '_build_episode_integrity_tab()',
        '_build_integrity_incident_ledger_tab()',
        '_build_integrity_alert_tab()',
        '_build_integrity_operations_console_tab()',
        '_build_episode_audit_tab()',
        '_build_error_tab()',
    ):
        assert direct_builder not in build_block


def test_qapplication_created_before_qt_backed_runtimes():
    text = Path('dvs_ai/app.py').read_text(encoding='utf-8')
    app_pos = text.index('app = QApplication.instance() or QApplication([])')
    runtime_markers = [
        'OrderFlowRuntime(',
        'LiveEpisodeCaptureRunner(',
        'CoreQualificationBatchRunner(',
    ]
    assert all(app_pos < text.index(marker) for marker in runtime_markers)
