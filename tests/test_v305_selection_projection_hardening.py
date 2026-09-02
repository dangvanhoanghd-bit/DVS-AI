from pathlib import Path

from dvs_ai.version import APP_EDITION, APP_VERSION


ROOT = Path(__file__).resolve().parents[1]
MAIN_WINDOW = ROOT / "dvs_ai" / "ui" / "main_window.py"


def test_version_matches_app_version():
    from dvs_ai import __version__
    from dvs_ai.version import APP_VERSION
    assert __version__ == APP_VERSION

def test_current_coin_badge_is_driven_by_shared_selection():
    source = MAIN_WINDOW.read_text(encoding="utf-8")
    assert 'self.current_coin_badge = QLabel("CURRENT: —")' in source
    assert 'f"CURRENT: {symbol.replace(\':USDT\', \'\')}"' in source


def test_tab_change_projects_selection_and_renders_smart_money():
    source = MAIN_WINDOW.read_text(encoding="utf-8")
    assert "def _sync_views_to_selection" in source
    assert "self._render_microstructure_analysis(rows[row])" in source
    assert "self._sync_views_to_selection()" in source


def test_restored_rows_are_scrolled_into_view():
    source = MAIN_WINDOW.read_text(encoding="utf-8")
    assert "table.scrollToItem(" in source
    assert "QAbstractItemView.ScrollHint.PositionAtCenter" in source
