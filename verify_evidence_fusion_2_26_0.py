from pathlib import Path
from dvs_ai.engines.evidence_fusion_engine import EvidenceFusionEngine, EvidenceSignal

root = Path(__file__).resolve().parent
assert '2.26.0-alpha' in (root/'dvs_ai/__init__.py').read_text()
engine = EvidenceFusionEngine()
base = engine.fuse([
    EvidenceSignal('FLOW', 'ORDER_FLOW', 80, .32),
    EvidenceSignal('MARKET', 'MARKET', 50, .12),
])
correlated = engine.fuse([
    EvidenceSignal('FLOW', 'ORDER_FLOW', 80, .32),
    EvidenceSignal('DURABILITY', 'ORDER_FLOW', 80, .10),
    EvidenceSignal('MARKET', 'MARKET', 50, .12),
])
assert base.active_weight == correlated.active_weight
assert base.score == correlated.score
assert not any(x in (root/'dvs_ai/engines/evidence_fusion_engine.py').read_text() for x in ('send_order(', 'TradeIntent', 'PositionSizer'))
print('EVIDENCE FUSION VERIFY 2.26.0: PASS')
