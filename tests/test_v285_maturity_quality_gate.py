from types import SimpleNamespace
from dvs_ai.domain.models import EntryStatus
from dvs_ai.engines.decision_engine import DecisionEngine

def frame(close=101.0, ema20=100.0, atr=1.0):
    return SimpleNamespace(close=close, ema20=ema20, atr=atr)

def test_maturity_gate_boundaries():
    assert DecisionEngine._maturity_gate(27.99) == "UNFORMED"
    assert DecisionEngine._maturity_gate(28.0) == "EARLY_FORMATION"
    assert DecisionEngine._maturity_gate(48.0) == "CONFIRMED"
    assert DecisionEngine._maturity_gate(68.0) == "LATE"
    assert DecisionEngine._maturity_gate(82.0) == "EXHAUSTION"

def test_early_entry_can_be_ready():
    assert DecisionEngine._entry_status(72,76,frame(close=101.2),"LONG",38,"EARLY_FORMATION","EARLY_FORMATION") == EntryStatus.READY

def test_first_retest_has_adaptive_extension_room():
    assert DecisionEngine._entry_status(72,76,frame(close=101.65),"LONG",55,"FIRST_RETEST","CONFIRMED") == EntryStatus.READY

def test_confirmed_extension_over_limit_is_running():
    assert DecisionEngine._entry_status(80,80,frame(close=101.81),"LONG",58,"CONFIRMED_TREND","CONFIRMED") == EntryStatus.RUNNING

def test_late_trend_never_ready():
    assert DecisionEngine._entry_status(90,90,frame(close=101.0),"LONG",72,"LATE_TREND","LATE") == EntryStatus.SETUP

def test_exhaustion_is_running():
    assert DecisionEngine._entry_status(90,90,frame(close=100.5),"LONG",88,"EXHAUSTION","EXHAUSTION") == EntryStatus.RUNNING

def test_short_extension_is_directional():
    assert DecisionEngine._directional_extension(frame(close=98.5),"SHORT") == 1.5
    assert DecisionEngine._directional_extension(frame(close=101.5),"SHORT") == 0.0

def test_quality_gate_downgrades_late_ready():
    status, reason = DecisionEngine._quality_gate(EntryStatus.READY,79,"LATE","LATE_TREND",0.8)
    assert status == EntryStatus.SETUP
    assert reason == "DOWNGRADE_LATE"

def test_quality_gate_blocks_extension():
    status, reason = DecisionEngine._quality_gate(EntryStatus.READY,40,"EARLY_FORMATION","EARLY_FORMATION",1.7)
    assert status == EntryStatus.RUNNING
    assert reason.startswith("BLOCK_EXTENSION_")
