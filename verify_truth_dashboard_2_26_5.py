from pathlib import Path

root = Path(__file__).resolve().parent
main = (root/'dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
dash = (root/'dvs_ai/ui/truth_dashboard.py').read_text(encoding='utf-8')
checks = {
    'version': 'APP_VERSION = "2.26.5"' in main,
    'real QWidget': 'class TruthDashboard(QWidget)' in dash,
    'real QFrame cards': 'class _TruthCard(QFrame)' in dash,
    'tab integration': 'self.tabs.addTab(self.truth_dashboard, "Truth Dashboard")' in main,
    'calibration': 'probability_calibration_state' in dash,
    'drift': 'calibration_drift_state' in dash,
    'order flow': 'order_flow_quality_gate' in dash,
    'reliability': 'evidence_reliability_summary' in dash,
    'observe only': all(x not in dash.lower() for x in ('send_order','tradeintent','positionsizer')),
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit('TRUTH DASHBOARD VERIFY FAIL: ' + ', '.join(failed))
print('TRUTH DASHBOARD VERIFY 2.26.5: PASS')
