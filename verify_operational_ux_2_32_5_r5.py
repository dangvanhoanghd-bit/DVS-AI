from pathlib import Path

root = Path(__file__).resolve().parent
main = (root / 'dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
truth = (root / 'dvs_ai/ui/truth_dashboard.py').read_text(encoding='utf-8')
service = (root / 'dvs_ai/services/operational_journey_service.py').read_text(encoding='utf-8')

assert 'Tổng PAPER' in main and 'đang mở' in main and 'đủ chuẩn Quantum' in main
assert 'display_state = "LEARNING" if learning_only else health.state' in truth
assert 'COLLECTING EVIDENCE' in truth and 'QUALITY GATE WAITING' in truth
assert 'AI Journey & Operational History' in truth
assert 'AI Health History' in truth and 'Evidence Outcome Accumulation' in truth
for forbidden in ('send_order', 'create_trade_intent', 'enable_testnet', 'live_execution'):
    assert forbidden not in service
print('OPERATIONAL UX & EVIDENCE JOURNEY VERIFIER 2.32.5-r5: PASS')
