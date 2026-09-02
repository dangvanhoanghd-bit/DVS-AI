from types import SimpleNamespace

from dvs_ai.engines.decision_engine import DecisionEngine


def test_long_pullback_is_not_running():
    r = SimpleNamespace(close=90.0, ema20=100.0, atr=2.0)
    status = DecisionEngine._entry_status(80, 75, r, "LONG")
    assert status.name != "RUNNING"


def test_short_pullback_is_not_running():
    r = SimpleNamespace(close=110.0, ema20=100.0, atr=2.0)
    status = DecisionEngine._entry_status(80, 75, r, "SHORT")
    assert status.name != "RUNNING"


def test_long_chase_is_running():
    r = SimpleNamespace(close=110.0, ema20=100.0, atr=2.0)
    status = DecisionEngine._entry_status(80, 75, r, "LONG")
    assert status.name == "RUNNING"


def test_short_chase_is_running():
    r = SimpleNamespace(close=90.0, ema20=100.0, atr=2.0)
    status = DecisionEngine._entry_status(80, 75, r, "SHORT")
    assert status.name == "RUNNING"
