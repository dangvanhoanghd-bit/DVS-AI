from dvs_ai.engines.evidence_fusion_engine import EvidenceFusionEngine, EvidenceSignal


def test_correlated_family_does_not_increase_vote_weight():
    engine = EvidenceFusionEngine()
    base = engine.fuse([
        EvidenceSignal('FOOTPRINT', 'ORDER_FLOW', 80, 0.32),
        EvidenceSignal('MARKET', 'MARKET', 50, 0.12),
    ])
    with_durability = engine.fuse([
        EvidenceSignal('FOOTPRINT', 'ORDER_FLOW', 80, 0.32),
        EvidenceSignal('DURABILITY', 'ORDER_FLOW', 80, 0.10),
        EvidenceSignal('MARKET', 'MARKET', 50, 0.12),
    ])
    assert with_durability.active_weight == base.active_weight
    assert with_durability.score == base.score


def test_missing_evidence_is_removed_and_weights_are_renormalized():
    result = EvidenceFusionEngine().fuse([
        EvidenceSignal('A', 'A', 80, 0.5),
        EvidenceSignal('MISSING', 'B', 0, 0.5, available=False),
    ])
    assert result.score == 80
    assert result.unavailable == ('MISSING',)


def test_quality_reduces_effective_weight_not_score_by_fake_zero_vote():
    result = EvidenceFusionEngine().fuse([
        EvidenceSignal('FLOW', 'FLOW', 90, 0.5, quality=0.2),
        EvidenceSignal('MARKET', 'MARKET', 50, 0.5, quality=1.0),
    ])
    assert result.active_weight == 1.0
    assert result.effective_weight == 0.6
    assert 50 < result.score < 90


def test_contradiction_cannot_be_averaged_into_ready_quality():
    result = EvidenceFusionEngine().fuse([
        EvidenceSignal('FLOW_CONFLICT', 'FLOW', 95, 0.5, contradiction=True),
        EvidenceSignal('ENTRY', 'ENTRY', 95, 0.5),
    ])
    assert result.score <= 68
    assert result.contradictions == ('FLOW_CONFLICT',)


def test_nan_and_infinite_scores_fail_safe():
    result = EvidenceFusionEngine().fuse([
        EvidenceSignal('NAN', 'A', float('nan'), 0.5),
        EvidenceSignal('INF', 'B', float('inf'), 0.5),
    ])
    assert result.score == 0
