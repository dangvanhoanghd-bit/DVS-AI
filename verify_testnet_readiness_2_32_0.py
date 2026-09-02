from pathlib import Path
p=Path('dvs_ai/services/testnet_readiness_service.py')
s=p.read_text(encoding='utf-8')
assert 'READY_FOR_MANUAL_TESTNET_REVIEW' in s
assert 'testnet_enabled: bool = False' in s
assert 'live_enabled: bool = False' in s
assert 'send_order' not in s and 'PositionSizer' not in s
print('TESTNET_READINESS_AUDIT_2.32.0: PASS')
