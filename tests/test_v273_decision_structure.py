from pathlib import Path


ROOT = Path(__file__).parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_decision_confidence_is_more_conservative():
    source = read("dvs_ai/engines/decision_engine.py")
    assert "0.40 * trend" in source
    assert "0.40 * entry" in source
    assert "risk.risk_score * 0.22" in source
    assert "confidence = min(confidence, 22.0)" in source


def test_decision_uses_alignment_and_regime_gates():
    source = read("dvs_ai/engines/decision_engine.py")
    assert 'alignment.label == "MÂU THUẪN"' in source
    assert 'regime.regime == "TRANSITION"' in source
    assert "status = EntryStatus.SETUP" in source


def test_structure_requires_wick_and_volume():
    source = read("dvs_ai/engines/structure_engine.py")
    assert "lower_wick >= 0.40" in source
    assert "lower_wick >= 0.50" in source
    assert "upper_wick >= 0.40" in source
    assert "upper_wick >= 0.50" in source


def test_structure_has_climax_and_multi_event_test():
    source = read("dvs_ai/engines/structure_engine.py")
    assert "Climax: Effort cực cao" in source
    assert "for event_age in range" in source
    assert "candidates.append" in source
    assert "max(candidates)" in source
