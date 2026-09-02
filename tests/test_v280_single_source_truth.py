from pathlib import Path

ROOT = Path(__file__).parents[1]


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_decision_gauge_uses_engine_confidence_only():
    source = read("dvs_ai/ui/main_window.py")
    start = source.index("def _update_pro_panels")
    end = source.index("def _build_backtest_tab", start)
    block = source[start:end]

    assert "float(a.confidence_score)" in block
    assert "0.45 * a.confidence_score" not in block
    assert "0.25 * direction_score" not in block
    assert "Confidence Score từ DecisionEngine.combine()" in block


def test_decision_gauge_title_is_confidence_score():
    source = read("dvs_ai/ui/main_window.py")
    assert 'GaugeWidget("CONFIDENCE SCORE")' in source


def test_15m_chart_uses_trade_plan_as_zone_source():
    source = read("dvs_ai/ui/market_chart.py")
    assert "plan_is_source" in source
    assert "float(self.trade_plan.entry_low)" in source
    assert "float(self.trade_plan.entry_high)" in source
    assert "and not plan_is_source" in source


def test_chart_no_longer_calls_old_candidate_helper():
    source = read("dvs_ai/ui/market_chart.py")
    assert "def _legacy_candidate_zones" in source
    assert "self._candidate_zones" not in source


def test_outcome_tracker_keeps_tp1_state_machine():
    source = read("dvs_ai/services/outcome_tracker.py")
    assert 'current_status = "TP1_HIT"' in source
    assert 'final_outcome = "PARTIAL_STOP"' in source
    assert "TP1 is not a final outcome" in source
