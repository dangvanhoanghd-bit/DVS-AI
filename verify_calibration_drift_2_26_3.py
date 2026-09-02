from pathlib import Path
root=Path(__file__).resolve().parent
assert '2.26.3-alpha' in (root/'dvs_ai/__init__.py').read_text()
assert 'APP_VERSION = "2.26.3"' in (root/'dvs_ai/ui/main_window.py').read_text()
service=(root/'dvs_ai/services/calibration_drift_monitor.py').read_text()
scanner=(root/'dvs_ai/services/scanner.py').read_text()
assert 'class CalibrationDriftMonitor' in service
assert 'INSUFFICIENT_DATA' in service and 'STABLE' in service and 'WATCH' in service and 'DRIFT' in service
assert 'calibration_drift_monitor.evaluate(force=True)' in scanner
assert 'calibration_drift_state=drift.state' in scanner
for forbidden in ('TradeIntent','PositionSizer','send_order'):
    assert forbidden not in service
print('CALIBRATION DRIFT VERIFY 2.26.3: PASS')
