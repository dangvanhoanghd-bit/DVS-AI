from __future__ import annotations

from pathlib import Path

from dvs_ai.scientific.ledger import InMemoryLedgerStorage, ScientificLedger
from dvs_ai.version import APP_VERSION, EXECUTION_STATUS_LABEL


def test_expert_mode_no_longer_calls_removed_show_analysis():
    source = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    start = source.index('    def _toggle_expert_mode')
    end = source.index('    def _apply_ux_mode', start)
    block = source[start:end]
    assert 'self.show_analysis' not in block
    assert 'show_selected' in block
    assert 'preserve_timeframe=True' in block
    assert 'preserve_scroll=True' in block
    assert 'UI_EXPERT_MODE_REFRESH_FAILED' in block


def test_verify_unknown_run_fails_closed():
    ledger = ScientificLedger(InMemoryLedgerStorage())
    assert ledger.verify_run('run-does-not-exist') is False


def test_version_matches_app_version():
    from dvs_ai import __version__
    from dvs_ai.version import APP_VERSION
    assert __version__ == APP_VERSION

def test_windows_launcher_identity_is_updated():
    launcher = Path('START_DVS_AI.bat').read_text(encoding='utf-8')
    assert APP_VERSION in launcher
    assert '2.32.0 Testnet Readiness Audit' not in launcher
