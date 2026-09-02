from types import SimpleNamespace

from dvs_ai.engines.evidence_fusion_engine import EvidenceFusionEngine, EvidenceSignal


def test_configurable_family_weights_are_defaults():
    engine = EvidenceFusionEngine(family_weights={"A": 0.8, "B": 0.2})
    result = engine.fuse([
        EvidenceSignal("a", "A", 100),
        EvidenceSignal("b", "B", 0),
    ])
    assert result.active_weight == 1.0
    assert result.score == 80.0


def test_unknown_reliability_is_neutral():
    engine = EvidenceFusionEngine(family_weights={"A": 1.0})
    unknown = engine.fuse([EvidenceSignal("a", "A", 80, reliability=None)])
    explicit_full = engine.fuse([EvidenceSignal("a", "A", 80, reliability=1.0)])
    assert unknown.score == explicit_full.score == 80.0
    assert unknown.effective_weight == explicit_full.effective_weight


def test_proxy_source_reduces_influence_not_direction():
    engine = EvidenceFusionEngine(family_weights={"FLOW": 0.5, "MARKET": 0.5})
    full = engine.fuse([
        EvidenceSignal("flow", "FLOW", 90, source="FULL"),
        EvidenceSignal("market", "MARKET", 50),
    ])
    proxy = engine.fuse([
        EvidenceSignal("flow", "FLOW", 90, source="PROXY"),
        EvidenceSignal("market", "MARKET", 50),
    ])
    assert proxy.score < full.score
    assert proxy.score > 50.0


def test_directional_contradiction_penalty_and_cap():
    engine = EvidenceFusionEngine(
        family_weights={"A": 0.5, "B": 0.5},
        contradiction_penalty=20.0,
        contradiction_cap=68.0,
    )
    result = engine.fuse([
        EvidenceSignal("positive", "A", 95),
        EvidenceSignal("opposing", "B", 90, contradiction=True, contradiction_strength=1.0),
    ])
    assert result.score <= 68.0
    assert result.directional_penalty > 0.0
    assert result.contradictions == ("opposing",)


def test_correlated_members_do_not_multiply_family_vote():
    engine = EvidenceFusionEngine(family_weights={"ORDER_FLOW": 0.32, "MARKET": 0.12})
    base = engine.fuse([
        EvidenceSignal("flow", "ORDER_FLOW", 70),
        EvidenceSignal("market", "MARKET", 70),
    ])
    expanded = engine.fuse([
        EvidenceSignal("flow", "ORDER_FLOW", 70),
        EvidenceSignal("durability", "ORDER_FLOW", 90),
        EvidenceSignal("market", "MARKET", 70),
    ])
    assert base.active_weight == expanded.active_weight == 0.44
