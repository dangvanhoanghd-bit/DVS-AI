from pathlib import Path

SOURCE = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')


def test_finalization_does_not_force_launch_time_tab():
    forbidden = 'self.tabs.setCurrentIndex(self._scan_view_tab)'
    assert forbidden not in SOURCE


def test_finalization_preserves_current_selection_not_launch_snapshot():
    assert 'current_row = self.table.currentRow()' in SOURCE
    assert 'selected_symbol = self._scan_view_symbol' not in SOURCE


def test_finalization_preserves_table_scroll_position():
    assert 'current_table_scroll = self.table.verticalScrollBar().value()' in SOURCE
    assert 'scroll_bar.setValue(min(current_table_scroll, scroll_bar.maximum()))' in SOURCE


def test_ui_refresh_is_debounced_for_interactive_use():
    assert 'self.stream_table_timer.setInterval(250)' in SOURCE
    assert 'self.aggregate_refresh_timer.setInterval(400)' in SOURCE
