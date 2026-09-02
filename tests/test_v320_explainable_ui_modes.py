from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'dvs_ai' / 'ui' / 'main_window.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'dvs_ai' / 'version.py').read_text(encoding='utf-8')


def test_version_matches_app_version():
    from dvs_ai import __version__
    from dvs_ai.version import APP_VERSION
    assert __version__ == APP_VERSION

def test_easy_and_expert_modes_have_distinct_widget_sets():
    assert 'smart_score_box' in MAIN
    assert 'smart_metrics_box' in MAIN
    assert 'smart_insight_container' in MAIN
    assert 'smart_timeline_box' in MAIN
    assert 'widget.setVisible(expert)' in MAIN
    assert 'widget.setVisible(not expert)' in MAIN


def test_decision_core_projects_from_shared_selection():
    assert 'def _render_decision_core_for_analysis' in MAIN
    sync = MAIN.split('def _sync_views_to_selection', 1)[1].split('def _on_tab_changed', 1)[0]
    assert '_render_smart_entry_for_analysis(analysis)' in sync
    assert '_render_decision_core_for_analysis(analysis)' in sync
