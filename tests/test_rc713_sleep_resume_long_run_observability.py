from pathlib import Path


def runtime_telemetry_source():
    return Path("dvs_ai/services/runtime_telemetry.py").read_text(encoding="utf-8")


def watchdog_source():
    return Path("dvs_ai/runtime/gui_hang_watchdog.py").read_text(encoding="utf-8")


def main_source():
    return Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")


def test_watchdog_distinguishes_process_wide_pause_from_gui_only_stall():
    text = watchdog_source()
    assert "watchdog_poll_gap_ms" in text
    assert "PROBABLE_PROCESS_WIDE_PAUSE" in text
    assert "GUI_THREAD_STALL_OR_BUSY" in text
    assert "process_wide_scheduling_gap_observed" in text


def test_memory_trend_uses_active_runtime_not_wall_time():
    text = runtime_telemetry_source()
    assert "_active_runtime_seconds" in text
    assert "active_increment_s = min(" in text
    assert "slope_mib_per_hour_30m" in text
    assert "slope_mib_per_hour_60m" in text
    assert "slope_mib_per_hour_120m" in text


def test_runtime_metrics_records_callback_gap_without_claiming_sleep():
    text = runtime_telemetry_source()
    assert "metrics_callback_gap_ms" in text
    assert "LONG_PROCESS_SCHEDULING_GAP" in text
    assert "OS_SLEEP" not in text


def test_prior_runtime_safety_features_remain():
    text = main_source()
    assert "worker_ownership_released" in text
    assert 'observation_source="shiboken_isValid_false"' in text
    assert "def _enqueue_result_dispatch" in text
    assert 'if not self._queued_pipeline_enabled("auto_paper"):' in text
    assert "semantic_owned_columns = set(range(3, 16))" in text


def test_no_unsafe_direct_worker_deletion_connection():
    assert "self.worker.finished.connect(self.worker.deleteLater)" not in main_source()
