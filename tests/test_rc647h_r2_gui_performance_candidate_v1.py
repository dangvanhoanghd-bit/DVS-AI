from pathlib import Path


def test_gui_refresh_dispatch_is_coalesced_and_non_bursting():
    source = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    assert 'self._gui_refresh_pending = set()' in source
    assert 'self._gui_refresh_queue = deque()' in source
    assert 'self.gui_refresh_dispatch_timer.setInterval(16)' in source
    assert 'self._schedule_standard_post_commit_refreshes("scan_finalization")' in source
    assert 'measurement_ms > self._gui_refresh_budget_ms' in source
    assert 'refresh_coalesced' in source


def test_outcome_refresh_uses_coalesced_dispatch():
    source = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    assert 'self._schedule_coalesced_gui_refresh("refresh_paper_trade_tab", "outcome_resolution_completed")' in source
    assert 'self._schedule_coalesced_gui_refresh("refresh_learning_center", "outcome_resolution_completed")' in source


def test_decision_engine_frozen_hash():
    import hashlib
    digest = hashlib.sha256(Path('dvs_ai/engines/decision_engine.py').read_bytes()).hexdigest()
    assert digest == '00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce'
