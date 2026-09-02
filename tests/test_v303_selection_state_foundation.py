from pathlib import Path

from dvs_ai.ui.selection_state import SelectionState, normalize_symbol
from dvs_ai.version import APP_VERSION, APP_EDITION


def test_symbol_normalization_is_stable():
    assert normalize_symbol(" sui/usdt:usdt ") == "SUI/USDT:USDT"
    assert normalize_symbol("") is None
    assert normalize_symbol(None) is None


def test_selection_state_tracks_symbol_timeframe_source_and_revision():
    state = SelectionState()
    first = state.select("sui/usdt:usdt", timeframe="1h", source="dashboard")
    assert first.symbol == "SUI/USDT:USDT"
    assert first.timeframe == "1h"
    assert first.source == "dashboard"
    assert first.revision == 1

    same = state.select("SUI/USDT:USDT", timeframe="1h", source="dashboard")
    assert same.revision == 1

    smart = state.select("near/usdt:usdt", source="smart_money")
    assert smart.symbol == "NEAR/USDT:USDT"
    assert smart.timeframe == "1h"
    assert smart.source == "smart_money"
    assert smart.revision == 2


def test_main_window_wires_dashboard_and_smart_money_to_shared_selection():
    source = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    assert "self.selection_state = SelectionState()" in source
    assert 'source="dashboard"' in source
    assert 'source="smart_money"' in source
    assert "sync_main_table=True" in source
    assert "selected_symbol = self.selection_state.symbol" in source


def test_version_matches_app_version():
    from dvs_ai import __version__
    from dvs_ai.version import APP_VERSION
    assert __version__ == APP_VERSION

