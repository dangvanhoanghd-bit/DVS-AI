from dvs_ai.engines.alignment_engine import MultiTimeframeEngine
from dvs_ai.engines.regime_engine import MarketRegimeEngine
from dvs_ai.engines.risk_engine import RiskEngine

def test_engines_construct():
    assert MultiTimeframeEngine() is not None
    assert MarketRegimeEngine() is not None
    assert RiskEngine() is not None
