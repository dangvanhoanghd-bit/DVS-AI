from pathlib import Path

from dvs_ai.version import APP_EDITION, APP_VERSION


ROOT = Path(__file__).resolve().parents[1]
MAIN_WINDOW = ROOT / "dvs_ai" / "ui" / "main_window.py"


def test_version_matches_app_version():
    from dvs_ai import __version__
    from dvs_ai.version import APP_VERSION
    assert __version__ == APP_VERSION

def test_history_and_paper_tables_publish_shared_selection():
    source = MAIN_WINDOW.read_text(encoding="utf-8")
    assert "self.history_table.itemSelectionChanged.connect" in source
    assert "self._select_history_symbol" in source
    assert "self.paper_table.itemSelectionChanged.connect" in source
    assert "self._select_paper_symbol" in source
    assert 'source="signal_history"' in source
    assert 'source="paper_trade"' in source


def test_shared_selection_is_restored_after_refresh_and_tab_change():
    source = MAIN_WINDOW.read_text(encoding="utf-8")
    assert "def _restore_table_symbol_selection" in source
    assert "def _on_tab_changed" in source
    assert "self.tabs.currentChanged.connect(self._on_tab_changed)" in source
    assert "self.history_table,\n            symbol_column=1" in source
    assert "self.paper_table,\n            symbol_column=3" in source


def test_table_selection_uses_analysis_context_when_available():
    source = MAIN_WINDOW.read_text(encoding="utf-8")
    assert "analysis = self.results.get(symbol)" in source
    assert "self._set_selected_analysis_context(" in source
    assert "sync_main_table=True" in source
