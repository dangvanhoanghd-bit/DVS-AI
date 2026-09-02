from pathlib import Path

ROOT = Path(__file__).resolve().parent
gate = (ROOT/'dvs_ai/services/order_flow_data_quality_gate.py').read_text(encoding='utf-8')
service = (ROOT/'dvs_ai/services/microstructure_service.py').read_text(encoding='utf-8')
execution = '\n'.join(p.read_text(encoding='utf-8', errors='ignore') for p in (ROOT/'dvs_ai/execution').glob('*.py'))
assert 'class OrderFlowDataQualityGate' in gate
assert 'STALE_ORDER_FLOW' in gate
assert 'UNRESOLVED_AGGTRADE_GAP' in gate
assert 'LIQUIDATION_GAP_INCOMPLETE' in gate
assert 'order_flow_allow_confirmation' in service
assert 'gate = "QUALITY_BLOCKED"' in service
assert 'OrderFlowDataQualityGate' not in execution
print('ORDER FLOW DATA QUALITY VERIFIER 2.25.4: PASS')
