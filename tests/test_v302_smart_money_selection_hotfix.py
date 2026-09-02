from pathlib import Path


def _source() -> str:
    return Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")


def test_smart_money_table_connects_selection_handler():
    source = _source()
    assert "self.micro_table.itemSelectionChanged.connect(" in source
    assert "self._show_selected_microstructure" in source


def test_selected_smart_money_row_renders_matching_analysis():
    source = _source()
    assert "row = self.micro_table.currentRow()" in source
    assert "analysis = rows[row]" in source
    assert "self._render_microstructure_analysis(analysis)" in source


def test_smart_money_selection_survives_refresh_by_symbol():
    source = _source()
    assert 'selected_symbol = getattr(previous_rows[current_row], "symbol", None)' in source
    assert "self.micro_table.selectRow(selected_row)" in source


def test_version_matches_app_version():
    from dvs_ai import __version__
    from dvs_ai.version import APP_VERSION
    assert __version__ == APP_VERSION

