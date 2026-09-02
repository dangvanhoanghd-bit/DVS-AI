from pathlib import Path


def test_batch_runner_has_persistent_thread_and_bounded_fifo_queue():
    source = Path('dvs_ai/ui/core_qualification_batch_runner.py').read_text(encoding='utf-8')
    assert 'self._thread = QThread(self)' in source
    assert 'max_pending_batches' in source
    assert 'QUEUE_FULL' in source
    assert 'self._queue.pop(0)' in source


def test_batch_runner_is_observe_only_and_has_no_authority_capabilities():
    source = Path('dvs_ai/ui/core_qualification_batch_runner.py').read_text(encoding='utf-8')
    for forbidden in (
        'submit_order(', 'place_order(', 'open_position(', 'switch_authority(',
        'activate_handover(', 'promote_authority(',
    ):
        assert forbidden not in source
    assert 'synthetic_lifecycle=True' in source
    assert 'classify_agreement_result' in source


def test_completed_scan_submits_all_results_without_user_selection():
    source = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    assert 'QTimer.singleShot(0, self._submit_qualification_batch)' in source
    assert 'for index, (symbol, analysis) in enumerate(self.results.items())' in source
    assert 'QualificationBatch.from_items' in source
    assert 'user selection is not required' in source


def test_batch_runtime_is_separate_from_interactive_shadow_adapter():
    app = Path('dvs_ai/app.py').read_text(encoding='utf-8')
    assert app.count('build_gui_shadow_core_runtime()') >= 2
    assert 'CoreRuntimeAdapter(build_gui_shadow_core_runtime())' in app
    assert 'CoreQualificationBatchRunner(' in app


def test_current_build_identity_is_dynamic_and_launcher_is_synchronized():
    from dvs_ai.version import APP_VERSION
    assert APP_VERSION
    launcher = Path("START_DVS_AI.bat").read_text(encoding="utf-8")
    assert APP_VERSION in launcher
