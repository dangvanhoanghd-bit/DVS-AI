from dataclasses import replace
from types import SimpleNamespace

from dvs_ai.domain.models import EntryStatus
from dvs_ai.services.microstructure_service import MicrostructureService


def analysis(status=EntryStatus.SETUP, confidence=60.0):
    return SimpleNamespace(
        confidence_score=confidence,
        entry_status=status,
        risk=SimpleNamespace(liquidation_safe=True),
        maturity_gate="EARLY_FORMATION",
        market_bias_gate="PASS",
        microstructure_gate="CONFIRMATION",
        microstructure=SimpleNamespace(
            composite_operator_score=80.0,
        ),
        reasons=(),
    )


def fake_replace(obj, **changes):
    data = dict(obj.__dict__)
    data.update(changes)
    return SimpleNamespace(**data)


def test_confirmation_bonus_is_bounded(monkeypatch):
    import dvs_ai.services.microstructure_service as module
    monkeypatch.setattr(module, "replace", fake_replace)
    out = MicrostructureService.apply_decision_adjustment(
        analysis(),
        weight=0.25,
        confirm_bonus=6.0,
        conflict_penalty=12.0,
    )
    assert 60.0 <= out.confidence_score <= 66.0


def test_confirmation_cannot_promote_wait(monkeypatch):
    import dvs_ai.services.microstructure_service as module
    monkeypatch.setattr(module, "replace", fake_replace)
    out = MicrostructureService.apply_decision_adjustment(
        analysis(status=EntryStatus.WAIT, confidence=48.0),
        weight=0.25,
        confirm_bonus=6.0,
        conflict_penalty=12.0,
    )
    assert out.entry_status == EntryStatus.WAIT
    assert out.confidence_score == 48.0


def test_strong_conflict_downgrades_ready(monkeypatch):
    import dvs_ai.services.microstructure_service as module
    monkeypatch.setattr(module, "replace", fake_replace)
    a = analysis(status=EntryStatus.READY, confidence=75.0)
    a.microstructure_gate = "STRONG_CONFLICT"
    out = MicrostructureService.apply_decision_adjustment(
        a,
        weight=0.25,
        confirm_bonus=6.0,
        conflict_penalty=12.0,
    )
    assert out.entry_status == EntryStatus.WAIT
    assert out.confidence_score < 75.0


def test_gate_has_seven_levels():
    source = open(
        "dvs_ai/services/microstructure_service.py",
        encoding="utf-8",
    ).read()
    for gate in (
        "STRONG_CONFIRMATION",
        "CONFIRMATION",
        "WEAK_CONFIRMATION",
        "OBSERVE",
        "WEAK_CONFLICT",
        "CONFLICT",
        "STRONG_CONFLICT",
    ):
        assert gate in source
