from pathlib import Path


def _source() -> str:
    return Path("dvs_ai/ui/truth_dashboard.py").read_text(encoding="utf-8")


def test_truth_dashboard_v3_has_scroll_and_readable_minimums() -> None:
    source = _source()
    assert "QScrollArea" in source
    assert "self.scroll_area.setWidgetResizable(True)" in source
    assert "self.setMinimumHeight(108)" in source
    assert "self.setMinimumHeight(230)" in source


def test_truth_dashboard_v3_reflows_cards_by_width() -> None:
    source = _source()
    assert "def _reflow_cards" in source
    assert "def resizeEvent" in source
    assert "width < 1050" in source
    assert "width < 1500" in source
    assert "self._reflow_cards(4)" in source


def test_truth_dashboard_v3_separates_runtime_and_history_refresh() -> None:
    source = _source()
    assert "HISTORY_REFRESH_SECONDS = 10.0" in source
    assert "force_history" in source
    assert "self._last_history_refresh" in source


def test_truth_dashboard_v3_has_commercial_empty_states_and_control_cards() -> None:
    source = _source()
    assert 'self.ai_health_card = _TruthCard("AI Health")' in source
    assert 'self.next_action_card = _TruthCard("Next Action")' in source
    assert "tiếp tục chạy PAPER" in source
    assert "Chưa có candidate/promotion history" in source


def test_truth_dashboard_v3_remains_observe_only() -> None:
    source = _source().lower()
    forbidden = (
        "send_order",
        "tradeintent",
        "positionsizer",
        "promote_to_main",
        "apply_shadow",
        "confidence_score =",
        "entry_status =",
    )
    assert not any(token in source for token in forbidden)
