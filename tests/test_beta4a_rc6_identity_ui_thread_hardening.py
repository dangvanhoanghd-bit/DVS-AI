from pathlib import Path


def _source():
    return Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")


def test_paper_outcome_network_work_is_not_called_from_gui_helpers():
    source = _source()
    update_block = source.split("def update_paper_trades(self):", 1)[1].split("def refresh_paper_trade_tab", 1)[0]
    deferred_block = source.split("def _refresh_paper_outcomes_deferred(self):", 1)[1].split("def _on_finalization_error", 1)[0]
    assert "update_open_trades" not in update_block
    assert "update_open_trades" not in deferred_block
    assert "outcome_resolution_coordinator.request_resolution()" in update_block
    assert "outcome_resolution_coordinator.request_resolution()" in deferred_block


def test_outcome_worker_completion_drives_render_only_after_commit():
    source = _source()
    assert "cycle_completed.connect(" in source
    assert "def _on_outcome_resolution_completed" in source
    assert "self.refresh_paper_trade_tab()" in source
    assert "self.refresh_learning_center()" in source


def test_identity_latency_and_queue_depth_are_observable():
    source = _source()
    assert "UNIFIED_IDENTITY_PUBLISHED" in source
    assert "latency_ms" in source
    assert "pending_count" in source
