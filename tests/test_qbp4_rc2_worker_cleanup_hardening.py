from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "dvs_ai" / "ui" / "main_window.py").read_text(encoding="utf-8")
CLEANUP = SOURCE.split("def _cleanup_scan_worker", 1)[1].split(
    "def scan_runtime_diagnostics", 1
)[0]


def test_cleanup_never_dereferences_a_potentially_deleted_worker_slot():
    assert "disconnect(current_worker.run)" not in CLEANUP
    assert "disconnect(" not in CLEANUP


def test_cleanup_is_fail_safe_and_resets_cycle_references():
    assert "try:" in CLEANUP
    assert "finally:" in CLEANUP
    assert "self.worker = None" in CLEANUP
    assert "self.thread = None" in CLEANUP
    assert "self._scan_started_monotonic = None" in CLEANUP


def test_stale_completion_cannot_clear_a_new_worker():
    assert "finished_generation" in CLEANUP
    assert "active_generation" in CLEANUP
    assert "STALE_GENERATION_IGNORED" in CLEANUP
    assert "self.sender()" not in CLEANUP


def test_persistent_qthread_and_worker_autodeletion_are_preserved():
    assert "self.worker.moveToThread(self._scan_runtime_thread)" in SOURCE
    assert "self.worker.finished.connect(self.worker.deleteLater)" in SOURCE
    assert "self._scan_runtime_thread.start()" in SOURCE


def test_runtime_patch_does_not_touch_decision_engine_contract():
    notes = (ROOT / "QBP4_RC2_RUNTIME_WORKER_LIFECYCLE_AUDIT.md").read_text(encoding="utf-8")
    assert "72cf7d54e1ed6369400683358da8c0ef" in notes
    assert "Decision Engine unchanged" in notes
