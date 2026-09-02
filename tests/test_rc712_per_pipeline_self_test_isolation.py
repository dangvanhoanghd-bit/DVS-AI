from pathlib import Path


def source() -> str:
    return Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")


def test_per_pipeline_gate_state_exists():
    text = source()
    assert 'self._queued_signal_pipeline_enabled = {' in text
    assert '"history": True' in text
    assert '"paper": True' in text
    assert '"auto_paper": True' in text


def test_finish_resolves_each_pipeline_independently():
    text = source()
    body = text[text.index("def _finish_queued_signal_self_test"):text.index("def _complete_prepare")]
    assert "pipeline: (pipeline in received)" in body
    assert "self._queued_signal_pipeline_enabled = dict(per_pipeline)" in body
    assert "all(per_pipeline.values())" in body


def test_auto_paper_checks_only_auto_paper_gate():
    text = source()
    assert 'if not self._queued_pipeline_enabled("auto_paper"):' in text
    auto_dispatch = text[text.index('if not self._queued_pipeline_enabled("auto_paper"):'):]
    assert "dispatch_blocked_pipeline_disabled" in auto_dispatch


def test_prepare_owner_checks_own_gate():
    text = source()
    body = text[text.index("def _emit_data_prepare"):text.index("def _write_data_prepare_event")]
    assert "if not self._queued_pipeline_enabled(owner):" in body


def test_no_business_logic_or_engine_changes_are_introduced_by_gate_test():
    text = source()
    assert "def _queued_pipeline_enabled" in text
    assert "worker_ownership_released" in text
    assert 'observation_source="shiboken_isValid_false"' in text
