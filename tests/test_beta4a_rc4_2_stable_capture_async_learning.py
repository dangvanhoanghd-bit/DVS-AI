from pathlib import Path


def test_main_window_uses_stable_capture_key_not_python_object_identity():
    source = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    assert '_capture_identity_by_key' in source
    assert 'self._capture_key(analysis, queue_scan_id)' in source
    assert '_capture_identity_by_analysis_id' not in source
    assert '_capture_failed_analysis_ids' not in source


def test_auto_paper_identity_delay_is_reconciled_without_opportunity_loss():
    source = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    assert '_auto_paper_identity_warning_seconds = 30.0' in source
    assert 'AUTO_PAPER_IDENTITY_DELAYED' in source
    assert 'AUTO_PAPER_IDENTITY_TIMEOUT' not in source
    assert 'deferred.append((analysis, capture_key, first_deferred_at))' in source


def test_learning_refresh_runs_in_dedicated_qthread():
    source = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    assert 'class LearningRefreshWorker(QObject)' in source
    assert 'self._learning_worker.moveToThread(self._learning_thread)' in source
    assert 'self._learning_refresh_requested.emit()' in source
    assert 'def _render_learning_payload' in source
