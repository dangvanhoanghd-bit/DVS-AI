from types import SimpleNamespace
from pathlib import Path

from dvs_ai.engines.decision_engine import DecisionEngine
from dvs_ai.domain.models import EntryStatus

ROOT = Path(__file__).parents[1]


def r15(close=101.0, ema20=100.0, atr=1.0):
    return SimpleNamespace(close=close, ema20=ema20, atr=atr)


def test_maturity_gate_boundaries():
    assert DecisionEngine._maturity_gate(20) == "UNFORMED"
    assert DecisionEngine._maturity_gate(35) == "EARLY_FORMATION"
    assert DecisionEngine._maturity_gate(55) == "CONFIRMED"
    assert DecisionEngine._maturity_gate(75) == "LATE"
    assert DecisionEngine._maturity_gate(90) == "EXHAUSTION"


def test_early_and_first_retest_can_be_ready():
    for lifecycle in ("EARLY_FORMATION", "FIRST_RETEST"):
        status = DecisionEngine._entry_status(
            72, 80, r15(), "LONG", 40, lifecycle
        )
        assert status == EntryStatus.READY


def test_confirmed_trend_can_be_ready_before_late_zone():
    status = DecisionEngine._entry_status(
        72, 80, r15(), "LONG", 60, "CONFIRMED_TREND"
    )
    assert status == EntryStatus.READY


def test_late_trend_downgrades_to_setup():
    status = DecisionEngine._entry_status(
        90, 90, r15(), "LONG", 79, "LATE_TREND"
    )
    assert status == EntryStatus.SETUP


def test_exhaustion_becomes_running():
    status = DecisionEngine._entry_status(
        90, 90, r15(), "LONG", 85, "EXHAUSTION"
    )
    assert status == EntryStatus.RUNNING


def test_short_is_directionally_symmetric():
    status = DecisionEngine._entry_status(
        72, 80, r15(close=99, ema20=100), "SHORT", 40,
        "EARLY_FORMATION",
    )
    assert status == EntryStatus.READY


def test_extension_blocks_ready_in_both_directions():
    assert DecisionEngine._entry_status(
        90, 90, r15(close=103.0), "LONG", 40, "EARLY_FORMATION"
    ) == EntryStatus.RUNNING
    assert DecisionEngine._entry_status(
        90, 90, r15(close=97.0), "SHORT", 40, "EARLY_FORMATION"
    ) == EntryStatus.RUNNING


def test_indicator_uses_confirmed_test_symmetrically():
    source=(ROOT/'dvs_ai/engines/indicator_engine.py').read_text(encoding='utf-8')
    assert 'confirmed_test = bool(test_confirmed)' in source
    assert 'if confirmed_test and cross_age <= 10' in source
    assert 'if confirmed_test or touches <= 2' in source


def test_tooltip_is_compact():
    source=(ROOT/'dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
    assert 'Strength {strength:.0f} · Maturity' in source
    assert 'Gate: {a.maturity_gate}' not in source
