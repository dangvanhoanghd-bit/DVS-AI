from pathlib import Path


def source() -> str:
    return Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')


def test_release_version_and_cell_diff_helpers_exist():
    text = source()
    assert 'from dvs_ai.version import' in text
    for token in (
        '_table_diff_metrics',
        'def table_diff_diagnostics',
        'def _ensure_table_item',
        'def _set_cell_display',
        'def _set_cell_background',
        'def _set_cell_foreground',
    ):
        assert token in text


def test_upsert_reuses_items_and_diffs_values():
    text = source()
    body = text[text.index('def _upsert_row'):text.index('def _apply_row_palette')]
    assert 'self._ensure_table_item(row, col)' in body
    assert 'self._set_cell_display(item, value)' in body
    assert 'QTableWidgetItem(str(value))' not in body
    assert 'self.table.setItem(row, col, item)' not in body


def test_semantic_highlights_are_after_base_palette():
    text = source()
    body = text[text.index('def _upsert_row'):text.index('def _apply_row_palette')]
    assert body.index('self._apply_row_palette(row, a)') < body.index('status_colors =')


def test_diff_metrics_are_profiled():
    text = source()
    assert 'self.ui_profiler.record("table_cell_diff", cell_elapsed_ms)' in text
    assert '"cells_checked"' in text
    assert '"cells_changed"' in text
    assert '"items_created"' in text
