from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "dvs_ai/ui/main_window.py").read_text(encoding="utf-8")



def test_executor_shutdown_is_waiting_and_authoritative():
    assert "executor.shutdown(\n                    wait=True," in SOURCE
    stop_block = SOURCE.split("    def stop(self):", 1)[1].split("\n\nclass FinalizationWorker", 1)[0]
    assert "executor.shutdown(" not in stop_block


def test_executor_thread_telemetry_is_named_and_bounded():
    assert 'thread.name.startswith("dvs-scan")' in SOURCE
    assert '"executor_drained": not after_names' in SOURCE
    assert '"dvs_scan_threads": dvs_scan_threads' in SOURCE
    assert "append(" not in SOURCE.split("def _on_scan_executor_lifecycle", 1)[1].split("def _cleanup_scan_worker", 1)[0]


def test_sleep_resume_gap_defers_auto_scan():
    assert "SYSTEM_RESUME_DETECTED" in SOURCE
    assert "if tick_gap >= 30.0:" in SOURCE
    block = SOURCE.split("if tick_gap >= 30.0:", 1)[1].split("if tick_gap >= 8.0:", 1)[0]
    assert "self.auto_scan_seconds = self.config.refresh_seconds" in block
    assert "return" in block


def test_auto_scan_enable_resets_tick_baseline():
    block = SOURCE.split("def toggle_auto_scan", 1)[1].split("def auto_scan_tick", 1)[0]
    assert "self._last_auto_tick_monotonic = time.monotonic()" in block


def test_provider_timeouts_remain_finite():
    provider = (ROOT / "dvs_ai/data/binance_provider.py").read_text(encoding="utf-8")
    assert 'timeout=(4.0, self.timeout)' in provider
    assert '"timeout": timeout_seconds * 1000' in provider
