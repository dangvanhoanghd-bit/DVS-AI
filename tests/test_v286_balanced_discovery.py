from types import SimpleNamespace
from pathlib import Path
import json

from dvs_ai.domain.models import EntryStatus
from dvs_ai.engines.decision_engine import DecisionEngine

ROOT = Path(__file__).parents[1]

def frame(close=101.0, ema20=100.0, atr=1.0):
    return SimpleNamespace(close=close, ema20=ema20, atr=atr)

def test_early_formation_becomes_setup():
    status = DecisionEngine._entry_status(
        50, 52, frame(), "LONG",
        maturity=38,
        lifecycle="EARLY_FORMATION",
        maturity_gate="EARLY_FORMATION",
    )
    assert status == EntryStatus.SETUP

def test_first_retest_can_ready():
    status = DecisionEngine._entry_status(
        60, 65, frame(close=101.2), "LONG",
        maturity=54,
        lifecycle="FIRST_RETEST",
        maturity_gate="CONFIRMED",
    )
    assert status == EntryStatus.READY

def test_late_and_extension_still_not_ready():
    late = DecisionEngine._entry_status(
        90, 90, frame(close=100.7), "LONG",
        maturity=72,
        lifecycle="LATE_TREND",
        maturity_gate="LATE",
    )
    extended = DecisionEngine._entry_status(
        70, 70, frame(close=102.0), "LONG",
        maturity=40,
        lifecycle="EARLY_FORMATION",
        maturity_gate="EARLY_FORMATION",
    )
    assert late == EntryStatus.SETUP
    assert extended == EntryStatus.RUNNING

def test_discovery_config():
    cfg=json.loads((ROOT/"config.json").read_text(encoding="utf-8"))
    assert cfg["main_confidence"] == 68
    assert cfg["main_entry"] == 62
    assert cfg["shadow_confidence"] == 45
    assert cfg["shadow_entry"] == 45
    assert cfg["shadow_risk_max"] == 65
    assert cfg["shadow_rr_min"] == 1.4
