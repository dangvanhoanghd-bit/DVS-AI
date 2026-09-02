from pathlib import Path

root = Path(__file__).resolve().parent
service = (root/'dvs_ai/services/probability_calibration_service.py').read_text()
scanner = (root/'dvs_ai/services/scanner.py').read_text()
models = (root/'dvs_ai/domain/models.py').read_text()
app = (root/'dvs_ai/app.py').read_text()

assert '2.26.1-alpha' in (root/'dvs_ai/__init__.py').read_text()
assert 'APP_VERSION = "2.26.1"' in (root/'dvs_ai/ui/main_window.py').read_text()
assert 'chronological' in service.lower()
assert '_pav' in service
assert 'REJECTED_VALIDATION' in service
assert 'INSUFFICIENT_DATA' in service
assert 'calibrated_probability' in models
assert 'annotate_calibrated_probabilities' in scanner
assert 'ProbabilityCalibrationService' in app
for forbidden in ('send_order', 'create_order', 'PositionSizer', 'TradeIntent'):
    assert forbidden not in service
print('PROBABILITY CALIBRATION VERIFY 2.26.1: PASS')
