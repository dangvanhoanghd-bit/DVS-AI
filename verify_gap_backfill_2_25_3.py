from pathlib import Path
ROOT=Path(__file__).resolve().parent
required=[
 ROOT/'dvs_ai/services/order_flow_gap_backfill.py',
 ROOT/'dvs_ai/services/order_flow_websocket_collector.py',
 ROOT/'tests/test_v2253_gap_detection_backfill.py',
]
for path in required: assert path.exists(), path
text=required[0].read_text(encoding='utf-8')
for token in ('max_gap_trades','non-contiguous','UNRESOLVED','realtime=False'):
    assert token in text, token
assert 'forceOrder' in text and 'never reconstructs' in text
collector=required[1].read_text(encoding='utf-8')
for token in ('gaps_detected','gaps_filled','gaps_unresolved','liquidation_gap_warnings'):
    assert token in collector, token
for forbidden in ('place_order','TradeIntent','PositionSizer'):
    assert forbidden not in text
print('GAP BACKFILL VERIFIER 2.25.3: PASS')
