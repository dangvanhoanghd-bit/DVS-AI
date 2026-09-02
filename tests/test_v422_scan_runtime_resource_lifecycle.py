from pathlib import Path


SOURCE = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")


def test_scan_qthread_is_parented_and_worker_objects_are_deleted():
    assert "self._scan_runtime_thread = QThread(self)" in SOURCE
    assert "self.worker.finished.connect(self.worker.deleteLater)" in SOURCE


def test_scan_worker_finished_signal_performs_reference_cleanup():
    assert "self.worker.finished_with_identity.connect(self._cleanup_scan_worker)" in SOURCE
    assert "def _cleanup_scan_worker(" in SOURCE
    assert "self.worker = None" in SOURCE
    assert "self.thread = None" in SOURCE


def test_scan_cleanup_rejects_stale_worker_signal():
    assert "finished_generation" in SOURCE
    assert "STALE_GENERATION_IGNORED" in SOURCE
    assert "self.sender()" not in SOURCE.split("def _cleanup_scan_worker", 1)[1].split("def scan_runtime_diagnostics", 1)[0]


def test_scan_telemetry_is_bounded_and_does_not_append_per_cycle():
    assert "self._scan_runtime_metrics = {" in SOURCE
    assert "def scan_runtime_diagnostics(self) -> dict:" in SOURCE
    assert "threading.active_count()" in SOURCE
    cleanup = SOURCE.split("def _cleanup_scan_worker", 1)[1].split("def stop_scan", 1)[0]
    assert ".append(" not in cleanup


def test_scan_algorithm_and_executor_policy_are_not_changed_by_lifecycle_fix():
    assert "self.service.scan_coin" in SOURCE
    assert 'thread_name_prefix=f"dvs-scan-g{self._executor_generation}"' in SOURCE
    assert "cancel_futures=True" in SOURCE


def test_release_scope_discloses_no_decision_engine_change():
    notes = Path("RELEASE_NOTES_4.2.2.md").read_text(encoding="utf-8")
    assert "Decision Engine" in notes
    assert "72cf7d54e1ed6369400683358da8c0ef" in notes
    assert "PAPER" in notes
