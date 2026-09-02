from pathlib import Path
from types import SimpleNamespace

from dvs_ai.engines.decision_engine import DecisionEngine
from dvs_ai.domain.models import EntryStatus

ROOT = Path(__file__).parents[1]


def read(rel):
    return (ROOT/rel).read_text(encoding="utf-8")


def test_late_trend_cannot_be_ready():
    r15 = SimpleNamespace(
        atr=1.0, close=110.0, ema20=100.0
    )
    status = DecisionEngine._entry_status(
        90, 90, r15, "LONG",
        maturity=84,
        lifecycle="EXHAUSTION",
    )
    assert status == EntryStatus.RUNNING


def test_early_formation_can_be_ready():
    r15 = SimpleNamespace(
        atr=1.0, close=101.0, ema20=100.0
    )
    status = DecisionEngine._entry_status(
        72, 80, r15, "LONG",
        maturity=38,
        lifecycle="EARLY_FORMATION",
    )
    assert status == EntryStatus.READY


def test_models_expose_maturity_fields():
    source = read("dvs_ai/domain/models.py")
    assert "long_trend_maturity" in source
    assert "trend_maturity_score" in source
    assert "trend_lifecycle" in source


def test_paper_tags_lifecycle():
    source = read("dvs_ai/services/paper_trade_service.py")
    assert 'tags.append(f"TREND_{lifecycle}")' in source
    assert "MATURITY_LATE" in source


def test_ui_displays_maturity():
    source = read("dvs_ai/ui/main_window.py")
    assert "MATURITY:" in source
    assert "Maturity" in source
