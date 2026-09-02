from __future__ import annotations

from dvs_ai.services.quantum_data_convergence.models import UnifiedOutcome
from dvs_ai.services.quantum_statistical_burn_in import (
    DatasetIntegrityAuditor,
    EffectiveSampleSizeEstimator,
    OutcomeQualificationEngine,
    StatisticalBurnInService,
    WalkForwardDatasetBuilder,
)


def snapshot():
    payload = {name: {"available": True, "score": 0.5, "quality": 1.0} for name in ("TIMING", "ENTRY", "ORDER_FLOW", "DIRECTION", "MARKET")}
    payload["_TRUTH"] = {"schema": "DVS_QUANTUM_TRAINING_V1", "calibration_state": "VALIDATED", "drift_state": "STABLE", "order_flow_quality": "FULL"}
    return payload


def row(i: int, *, provenance=None, outcome=None, direction=None):
    return UnifiedOutcome(
        source="paper_trades", source_id=str(i), symbol="BTCUSDT" if i < 9 else "ETHUSDT",
        direction=direction or ("LONG" if i % 2 else "SHORT"), setup_time=f"2026-01-{i+1:02d}T00:00:00Z",
        close_time=f"2026-01-{i+1:02d}T01:00:00Z", outcome=outcome or ("WIN" if i % 2 else "LOSS"),
        realized_r=1.0 if i % 2 else -1.0, regime="TREND" if i % 2 else "RANGE",
        evidence_snapshot=snapshot(), provenance=provenance or {},
    )


def test_qualification_has_three_states():
    rows = [row(1), row(2, provenance={"review_required": True}), row(3, outcome="AMBIGUOUS")]
    result = OutcomeQualificationEngine().evaluate(rows)
    assert (result.qualified, result.pending_review, result.rejected) == (1, 1, 1)
    assert {item.status for item in result.records} == {"QUALIFIED", "PENDING_REVIEW", "REJECTED"}


def test_ess_is_bounded_and_deterministic():
    result = EffectiveSampleSizeEstimator.estimate([1, -1, 1, -1, 1, -1])
    assert 1 <= result.ess <= result.n
    assert result.method == "AR1_CONSERVATIVE_V1"
    assert EffectiveSampleSizeEstimator.estimate([1]).state == "INSUFFICIENT_DATA"


def test_walk_forward_has_no_train_test_overlap_and_gaps_are_explicit():
    q = OutcomeQualificationEngine().evaluate([row(i) for i in range(12)])
    plan = WalkForwardDatasetBuilder().build(q.records, folds=3, purge=1, embargo=1)
    assert plan.state == "READY"
    for fold in plan.folds:
        assert not (set(fold.train_identities) & set(fold.test_identities))
        assert not (set(fold.purged_identities) & set(fold.test_identities))


def test_integrity_warns_on_concentration():
    result = OutcomeQualificationEngine().evaluate([row(i) for i in range(10)])
    report = DatasetIntegrityAuditor().inspect(result)
    assert "SYMBOL_CONCENTRATION_ABOVE_80_PERCENT" in report.warnings


def test_statistical_service_remains_locked_below_100():
    report = StatisticalBurnInService().evaluate([row(i) for i in range(20)])
    assert report.state == "QBP2_COLLECTION_OR_REVIEW_REQUIRED"
    assert report.capabilities["effective_sample_size"] is False
    assert report.authority_granted is False
    assert report.production_or_execution_authority is False


def test_statistical_service_unlocks_research_capabilities_at_100_only():
    rows = []
    for i in range(100):
        r = row(i % 20)
        rows.append(UnifiedOutcome(**{**r.__dict__, "source_id": str(i), "symbol": "BTCUSDT" if i % 2 else "ETHUSDT"}))
    report = StatisticalBurnInService().evaluate(rows)
    assert all(report.capabilities.values())
    assert report.authority_granted is False
    assert report.production_or_execution_authority is False
