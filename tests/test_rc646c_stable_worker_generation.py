from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
WORKER = SOURCE.split("class Worker(QObject):", 1)[1].split("class FinalizationWorker", 1)[0]
CLEANUP = SOURCE.split("def _cleanup_scan_worker", 1)[1].split("def scan_runtime_diagnostics", 1)[0]

def test_completion_payload_is_copied_before_legacy_finished_signal():
    assert "finished_with_identity = Signal(int, str, int)" in WORKER
    snapshot = WORKER.index("finished_generation = int(self.generation)")
    identity_emit = WORKER.index("self.finished_with_identity.emit")
    legacy_emit = WORKER.index("self.finished.emit()")
    assert snapshot < identity_emit < legacy_emit

def test_cleanup_authority_never_uses_qobject_sender_identity():
    assert "self.sender()" not in CLEANUP
    assert " id(" not in CLEANUP
    assert "finished_generation" in CLEANUP
    assert "active_generation" in CLEANUP
    assert "identity_payload_matches" in CLEANUP

def test_stale_generation_returns_before_reference_reset():
    guard = CLEANUP.index("if not identity_payload_matches:")
    stale_return = CLEANUP.index("return", guard)
    reset = CLEANUP.index("self.worker = None")
    assert guard < stale_return < reset

def test_launch_assigns_monotonic_generation_and_connects_cleanup_first():
    launch = SOURCE.split("def _launch_scan", 1)[1].split("def _on_scan_executor_lifecycle", 1)[0]
    assert "self._scan_worker_generation += 1" in launch
    assert "generation=generation" in launch
    identity_connect = launch.index("finished_with_identity.connect(self._cleanup_scan_worker)")
    on_finished_connect = launch.index("finished.connect(self.on_finished)")
    delete_connect = launch.index("finished.connect(self.worker.deleteLater)")
    assert identity_connect < on_finished_connect < delete_connect

def test_object_identity_is_observational_only():
    assert "worker_object_id=hex(id(self.worker))" in SOURCE
    assert "self.sender()" not in CLEANUP
