from pathlib import Path
root=Path(__file__).resolve().parent
service=(root/'dvs_ai/services/adaptive_confidence_service.py').read_text()
scanner=(root/'dvs_ai/services/scanner.py').read_text()
models=(root/'dvs_ai/domain/models.py').read_text()
assert '2.26.3-alpha' in (root/'dvs_ai/__init__.py').read_text()
assert 'APP_VERSION = "2.26.3"' in (root/'dvs_ai/ui/main_window.py').read_text()
assert 'class AdaptiveConfidenceService' in service
assert 'REJECTED_VALIDATION' in service
assert 'max_adjustment' in service
assert 'adaptive_probability=adaptive.probability' in scanner
assert 'confidence_score=adaptive.probability' not in scanner
assert 'adaptive_probability: float = 0.0' in models
for forbidden in ('send_order', 'TradeIntent', 'PositionSizer'):
    assert forbidden not in service
print('ADAPTIVE CONFIDENCE VERIFY 2.26.3: PASS')
