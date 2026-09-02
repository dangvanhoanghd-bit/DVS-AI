from pathlib import Path

ROOT=Path(__file__).resolve().parent
required=[
    ROOT/'dvs_ai/services/order_flow_websocket_collector.py',
    ROOT/'tests/test_v2252_resilient_websocket_collector.py',
]
for path in required:
    assert path.exists(), path
text=required[0].read_text(encoding='utf-8')
for token in ('stale_after_seconds','reconnect_max_seconds','process_message','@forceOrder','evidence'):
    assert token in text, token
assert 'place_order' not in text
print('ORDER FLOW WEBSOCKET VERIFIER 2.25.2: PASS')
