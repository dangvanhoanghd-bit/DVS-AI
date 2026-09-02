from types import SimpleNamespace
from dvs_ai.engines.decision_engine import DecisionEngine

def test_long_trade_plan_invariant():
    r=SimpleNamespace(atr=1.0,support=100.0,resistance=105.0)
    p=DecisionEngine._trade_plan('LONG',99.0,r)
    assert p.invalidation<p.entry_low<p.entry_high<p.tp1<p.tp2

def test_short_trade_plan_invariant():
    r=SimpleNamespace(atr=1.0,support=95.0,resistance=100.0)
    p=DecisionEngine._trade_plan('SHORT',101.0,r)
    assert p.tp2<p.tp1<p.entry_low<p.entry_high<p.invalidation
