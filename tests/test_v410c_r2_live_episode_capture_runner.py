from pathlib import Path


def _source(path):
    return Path(path).read_text(encoding="utf-8")


def test_runner_uses_one_persistent_qthread_and_bounded_fifo():
    source = _source("dvs_ai/ui/live_episode_capture_runner.py")
    assert "self._thread = QThread(self)" in source
    assert "self._queue = deque()" in source
    assert "max_pending: int = 512" in source
    assert "QUEUE_FULL" in source
    assert ".terminate(" not in source


def test_main_window_submits_without_synchronous_capture_on_runner_path():
    source = _source("dvs_ai/ui/main_window.py")
    assert 'submit = getattr(self.live_episode_capture, "submit", None)' in source
    assert "if not submit(a):" in source
    assert "Live episode capture submit failed" in source


def test_runner_has_safe_shutdown_and_app_wires_it():
    runner = _source("dvs_ai/ui/live_episode_capture_runner.py")
    app = _source("dvs_ai/app.py")
    window = _source("dvs_ai/ui/main_window.py")
    assert "self._thread.quit()" in runner
    assert "self._thread.wait(timeout_ms)" in runner
    assert "LiveEpisodeCaptureRunner(live_episode_capture)" in app
    assert 'close_capture(timeout_ms=5000)' in window
