from pathlib import Path


def source() -> str:
    return Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")


def test_stream_results_are_buffered_instead_of_sorted_per_symbol():
    text = source()
    body = text[text.index("def on_result"):text.index("def _restore_scroll_value")]
    assert "self._schedule_stream_table_update(a)" in body
    assert "self._upsert_row(a)" not in body


def test_stream_batch_disables_sorting_signals_and_repaint_once():
    text = source()
    body = text[text.index("def _flush_stream_table_updates"):text.index("@Slot(object)\n    def on_result")]
    assert "self.table.setUpdatesEnabled(False)" in body
    assert "self.table.blockSignals(True)" in body
    assert "self.table.setSortingEnabled(False)" in body
    assert "self._upsert_row(analysis, manage_sorting=False)" in body
    assert body.count("self._rebuild_row_index()") == 1
    assert body.count("self.table.sortItems(") == 1
    assert "stream_table_batch_commit" in body
    assert "stream_table_sort" in body
    assert "stream_row_index_rebuild" in body


def test_scan_finish_flushes_pending_table_batch_before_finalization():
    text = source()
    body = text[text.index("def on_finished"):text.index("def _start_async_finalization")]
    assert body.index("self._flush_stream_table_updates()") < body.index("self._start_async_finalization()")


def test_upsert_profiler_includes_sort_and_index_cost_when_used_standalone():
    text = source()
    body = text[text.index("def _upsert_row"):text.index("def _apply_row_palette")]
    assert "table_cell_diff" in body
    assert "table_sort" in body
    assert "row_index_rebuild" in body
    assert body.index("table_sort") < body.index("row_index_rebuild")
