from pathlib import Path
import json
root=Path(__file__).parent
service=(root/'dvs_ai/services/operational_validation_service.py').read_text()
ui=(root/'dvs_ai/ui/truth_dashboard.py').read_text()
cfg=json.loads((root/'config.json').read_text())
assert 'DEFAULT_WEIGHTS' in service
assert '_validate_weights' in service
assert 'DEFAULT_MODIFIERS' in service
assert 'COMPOSITE_EVIDENCE_INCIDENT' in service
assert 'impact: str' in service
assert 'active_regime' in service
assert 'operational_health_weights' in cfg
assert 'operational_regime_modifiers' in cfg
for token in ('send_order','TradeIntentBuilder','PositionSizer','ShadowPromotionService'):
    assert token not in service
assert 'health_weights=_op_cfg.get' in ui
print('Operational Validation Hardening 2.31.1: PASS')
