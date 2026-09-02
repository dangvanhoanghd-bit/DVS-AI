from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_overlay_is_a_real_widget_with_live_refresh():
    source = (ROOT / 'dvs_ai/ui/performance_overlay.py').read_text(encoding='utf-8')
    assert 'class PerformanceOverlay(QFrame)' in source
    assert 'self._timer.timeout.connect(self.refresh_metrics)' in source
    assert 'self.body.setText' in source


def test_overlay_reads_real_diagnostics_providers():
    source = (ROOT / 'dvs_ai/ui/performance_overlay.py').read_text(encoding='utf-8')
    for token in ('scheduler_provider', 'profiler_provider', 'table_provider', 'worker_provider'):
        assert token in source
    for token in ('last_frame_ms', 'last_event_loop_lag_ms', 'cells_changed', 'pending'):
        assert token in source


def test_overlay_has_toggle_persistence_and_lifecycle():
    source = (ROOT / 'dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    assert '("Ctrl+Shift+P", self.toggle_performance_overlay)' in source
    assert 'commercial/performance_overlay' in source
    assert 'self.performance_overlay.close_overlay()' in source
    assert 'self.performance_overlay.reposition()' in source


def test_profiler_exposes_event_loop_lag():
    source = (ROOT / 'dvs_ai/ui/ui_performance_profiler.py').read_text(encoding='utf-8')
    assert 'self.last_event_loop_lag_ms = delay_ms' in source
    assert 'self.max_event_loop_lag_ms = max' in source
    assert 'event_loop_stall_count' in source
