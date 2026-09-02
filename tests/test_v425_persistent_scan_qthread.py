from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "dvs_ai" / "ui" / "main_window.py").read_text(encoding="utf-8")


def test_one_persistent_native_scan_thread_is_created():
    assert 'self._scan_runtime_thread = QThread(self)' in MAIN
    assert 'setObjectName("dvs-scan-runtime")' in MAIN
    assert 'self._scan_runtime_thread.start()' in MAIN


def test_scan_cycles_reuse_persistent_thread_and_delete_only_worker():
    assert 'self.worker.moveToThread(self._scan_runtime_thread)' in MAIN
    assert 'self._scan_run_requested.connect(self.worker.run, Qt.QueuedConnection)' in MAIN
    assert 'self.worker.finished_with_identity.connect(self._cleanup_scan_worker)' in MAIN
    assert 'self.worker.finished.connect(self.worker.deleteLater)' in MAIN
    scan_block = MAIN.split('self.current_scan_id =', 1)[1].split('@Slot(object)', 1)[0]
    assert 'QThread(self)' not in scan_block
    assert 'self.thread.quit' not in scan_block


def test_deleted_worker_is_not_dereferenced_during_cleanup():
    cleanup = MAIN.split('def _cleanup_scan_worker', 1)[1].split('def scan_runtime_diagnostics', 1)[0]
    assert 'disconnect(current_worker.run)' not in cleanup
    assert 'copied primitive identity values only' in cleanup
    assert 'self.sender()' not in cleanup
    assert 'self.worker = None' in cleanup
    assert 'self.thread = None' in cleanup
    assert 'finally:' in cleanup


def test_persistent_thread_is_joined_on_close():
    close = MAIN.split('def closeEvent', 1)[1].split('def ', 1)[0]
    assert 'scan_runtime_thread.quit()' in close
    assert 'scan_runtime_thread.wait(6000)' in close



def test_decision_engine_remains_frozen():
    notes = (ROOT / 'RELEASE_NOTES_4.2.5.md').read_text(encoding='utf-8')
    assert '72cf7d54e1ed6369400683358da8c0ef' in notes
    assert 'Decision Engine unchanged' in notes
