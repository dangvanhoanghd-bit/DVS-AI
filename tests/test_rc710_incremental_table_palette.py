from pathlib import Path


def source() -> str:
    return Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")


def test_stream_batching_semantics_remain():
    text = source()
    start = text.index("def _flush_stream_table_updates")
    end = text.index("def on_result", start)
    body = text[start:end]
    assert "self.table.setUpdatesEnabled(False)" in body
    assert "self.table.blockSignals(True)" in body
    assert "self._upsert_row(analysis, manage_sorting=False)" in body
    assert body.count("self._rebuild_row_index()") == 1
    assert body.count("self.table.sortItems(") == 1


def test_stream_update_is_still_scheduled_from_side_effect_drain():
    text = source()
    assert "self._schedule_stream_table_update(analysis)" in text


def test_unchanged_row_skips_before_widget_mutation():
    text = source()
    body = text[text.index("def _upsert_row"):text.index("def _semantic_background")]
    assert "fingerprint = self._analysis_table_fingerprint(a)" in body
    assert '"rows_unchanged_skipped"' in body
    assert body.index('"rows_unchanged_skipped"') < body.index("self.table.insertRow")


def test_semantic_palette_owns_columns_3_through_15():
    text = source()
    body = text[text.index("def _apply_row_palette"):text.index("def _refresh_error_table")]
    assert "semantic_owned_columns = set(range(3, 16))" in body
    assert 'if col not in semantic_owned_columns:' in body
    assert '"palette_base_writes_avoided"' in body


def test_previous_safety_guards_remain():
    text = source()
    assert "worker_ownership_released" in text
    assert 'observation_source="shiboken_isValid_false"' in text
    assert "def _enqueue_result_dispatch" in text
    assert "self.worker.finished.connect(self.worker.deleteLater)" not in text
