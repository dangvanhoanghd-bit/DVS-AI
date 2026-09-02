from dvs_ai.engines.decision_engine import DecisionEngine

def test_oi_classification():
    e=DecisionEngine()
    assert e.classify_oi(1,1)=="Long build-up"
    assert e.classify_oi(-1,1)=="Short build-up"
    assert e.classify_oi(1,-1)=="Short covering"
    assert e.classify_oi(-1,-1)=="Long unwinding"
