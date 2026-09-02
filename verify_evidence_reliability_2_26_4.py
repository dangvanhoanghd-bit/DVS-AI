from pathlib import Path

root=Path(__file__).resolve().parent
required=[
 'dvs_ai/services/evidence_reliability_service.py',
 'tests/test_v2264_evidence_reliability_truth_audit.py',
]
for name in required:
    assert (root/name).exists(), name
service=(root/'dvs_ai/services/evidence_reliability_service.py').read_text()
assert 'TIME_DECAY_BAYES_HIERARCHICAL' in service
assert 'UNKNOWN' in service
assert 'TradeIntent' not in service and 'PositionSizer' not in service and 'send_order' not in service
paper=(root/'dvs_ai/services/paper_trade_service.py').read_text()
assert 'evidence_snapshot_json' in paper
assert '_evidence_snapshot' in paper
fusion=(root/'dvs_ai/engines/evidence_fusion_engine.py').read_text()
assert 'reliability' not in fusion.lower(), '2.26.4 must remain observe-only'
print('Evidence Reliability 2.26.4 verifier: PASS')
