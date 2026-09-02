from pathlib import Path


def test_truth_dashboard_module_is_real_ui():
    source = Path('dvs_ai/ui/truth_dashboard.py').read_text(encoding='utf-8')
    assert 'class TruthDashboard(QWidget)' in source
    assert 'class _TruthCard(QFrame)' in source
    assert 'QTableWidget' in source
    assert 'calibration_drift_state' in source
    assert 'evidence_reliability_summary' in source
    assert 'order_flow_quality_gate' in source


def test_main_window_integrates_truth_dashboard_observe_only():
    source = Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    assert 'from dvs_ai.version import' in source
    assert 'self._build_truth_dashboard_tab()' in source
    assert 'self.tabs.addTab(self.truth_dashboard, "Truth Dashboard")' in source
    block = Path('dvs_ai/ui/truth_dashboard.py').read_text(encoding='utf-8').lower()
    for forbidden in ('send_order', 'tradeintent', 'positionsizer', 'entry_status =', 'confidence_score ='):
        assert forbidden not in block


def test_dashboard_surfaces_truth_fields():
    source = Path('dvs_ai/ui/truth_dashboard.py').read_text(encoding='utf-8')
    required = (
        'probability_calibration_state', 'calibrated_probability',
        'adaptive_probability', 'adaptive_confidence_state',
        'calibration_drift_state', 'calibration_drift_brier_delta',
        'confidence_fusion_method', 'decision_quality_score',
        'evidence_reliability_summary', 'gaps_unresolved',
    )
    for field in required:
        assert field in source
