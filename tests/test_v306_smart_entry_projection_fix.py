from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'dvs_ai' / 'ui' / 'main_window.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'dvs_ai' / 'version.py').read_text(encoding='utf-8')


def test_version_matches_app_version():
    from dvs_ai import __version__
    from dvs_ai.version import APP_VERSION
    assert __version__ == APP_VERSION

def test_selection_projection_resolves_cached_analysis():
    assert 'def _analysis_for_selected_symbol(self):' in MAIN
    assert 'analysis = self._analysis_for_selected_symbol()' in MAIN
    assert 'self.current_analysis = analysis' in MAIN


def test_smart_entry_has_dedicated_renderer():
    assert 'def _render_smart_entry_for_analysis(self, analysis) -> bool:' in MAIN
    assert 'self.smart_title.setText' in MAIN
    assert 'self.smart_summary.setHtml' in MAIN
    assert 'self.smart_text.setPlainText' in MAIN


def test_cross_tab_sync_projects_smart_entry():
    sync_start = MAIN.index('def _sync_views_to_selection')
    tab_start = MAIN.index('def _on_tab_changed', sync_start)
    sync_body = MAIN[sync_start:tab_start]
    assert 'self._render_smart_entry_for_analysis(analysis)' in sync_body


def test_full_detail_view_reuses_smart_entry_renderer():
    show_start = MAIN.index('def _show_selected_impl')
    assert 'self._render_smart_entry_for_analysis(a)' in MAIN[show_start:]
