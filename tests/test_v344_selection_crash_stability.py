from pathlib import Path


def test_adapter_uses_one_persistent_qthread():
    source = Path('dvs_ai/ui/core_runtime_adapter.py').read_text(encoding='utf-8')
    assert 'self._thread = QThread(self)' in source
    assert 'def _start(' not in source
    assert 'thread.deleteLater' not in source
    assert 'self._request_worker.emit(request)' in source


def test_selection_render_has_non_reentrant_crash_guard():
    source = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    assert 'self._selection_render_active' in source
    assert 'log_gui_exception(context="show_selected"' in source
    assert 'QTimer.singleShot(0, self.show_selected)' in source


def test_global_python_and_native_fault_reporting_installed():
    app = Path('dvs_ai/app.py').read_text(encoding='utf-8')
    crash = Path('dvs_ai/ui/crash_reporting.py').read_text(encoding='utf-8')
    assert 'install_global_exception_reporting()' in app
    assert 'sys.excepthook = hook' in crash
    assert 'faulthandler.enable' in crash
    assert 'logs' in crash


def test_crash_stability_remains_in_current_build():
    source = Path('dvs_ai/ui/core_runtime_adapter.py').read_text(encoding='utf-8')
    assert 'one persistent QThread' in source
