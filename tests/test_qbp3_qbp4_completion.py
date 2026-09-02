from __future__ import annotations

from dataclasses import replace

from dvs_ai.services.quantum_data_convergence.models import UnifiedOutcome
from dvs_ai.services.quantum_statistical_validation import (
    ChronologicalStabilityValidator,
    DeterministicBootstrapValidator,
    HolmBonferroniController,
    QuantumGovernanceHandoverService,
    QuantumStatisticalValidationService,
)


def snapshot():
    payload = {name: {"available": True, "score": 0.5, "quality": 1.0} for name in ("TIMING", "ENTRY", "ORDER_FLOW", "DIRECTION", "MARKET")}
    payload["_TRUTH"] = {"schema": "DVS_QUANTUM_TRAINING_V1", "calibration_state": "VALIDATED", "drift_state": "STABLE", "order_flow_quality": "FULL"}
    return payload


def rows(n: int):
    result = []
    for i in range(n):
        result.append(UnifiedOutcome(
            source="paper_trades", source_id=str(i), symbol="BTCUSDT" if i % 2 else "ETHUSDT",
            direction="LONG" if i % 2 else "SHORT", setup_time=f"2026-{(i // 28) % 12 + 1:02d}-{i % 28 + 1:02d}T00:00:00Z",
            close_time=f"2026-{(i // 28) % 12 + 1:02d}-{i % 28 + 1:02d}T01:00:00Z",
            outcome="WIN" if i % 3 else "LOSS", realized_r=1.2 if i % 3 else -1.0,
            regime="TREND" if i % 2 else "RANGE", evidence_snapshot=snapshot(), provenance={},
        ))
    return result


def test_bootstrap_is_locked_below_300_and_deterministic_at_300():
    validator = DeterministicBootstrapValidator()
    assert validator.evaluate([1.0] * 299, dataset_sha256="a").state == "LOCKED_INSUFFICIENT_DATA"
    first = validator.evaluate([1.0, -1.0, 1.0] * 100, dataset_sha256="b", iterations=200)
    second = validator.evaluate([1.0, -1.0, 1.0] * 100, dataset_sha256="b", iterations=200)
    assert first == second
    assert first.state == "READY"


def test_stability_windows_do_not_overlap():
    qbp3 = QuantumStatisticalValidationService().evaluate(rows(300), candidate_p_values={"A": 0.01}, bootstrap_iterations=200)
    windows = qbp3.stability["windows"]
    identities = [identity for window in windows for identity in window["identities"]]
    assert len(identities) == len(set(identities)) == 300


def test_holm_bonferroni_is_monotonic_and_controls_family():
    report = HolmBonferroniController().evaluate({"A": 0.01, "B": 0.03, "C": 0.2})
    adjusted = [item.adjusted_p_value for item in report.items]
    assert adjusted == sorted(adjusted)
    assert report.items[0].rejected is True
    assert report.items[-1].rejected is False


def test_qbp3_locked_below_300_and_never_grants_authority():
    report = QuantumStatisticalValidationService().evaluate(rows(299), candidate_p_values={"A": 0.01}, bootstrap_iterations=200)
    assert report.state == "QBP3_LOCKED_OR_REVIEW_REQUIRED"
    assert report.authority_granted is False
    assert report.production_or_execution_authority is False


def test_qbp4_requires_500_and_qbp3_clear():
    service = QuantumStatisticalValidationService()
    handover = QuantumGovernanceHandoverService()
    below = handover.evaluate(service.evaluate(rows(499), candidate_p_values={"A": 0.01}, bootstrap_iterations=200))
    assert below.paper_authority_handover_eligible is False
    ready = handover.evaluate(service.evaluate(rows(500), candidate_p_values={"A": 0.01}, bootstrap_iterations=200))
    assert ready.state == "QBP4_HUMAN_GOVERNANCE_REVIEW_ELIGIBLE"
    assert ready.paper_authority_handover_eligible is True
    assert ready.paper_authority_handover_granted is False
    assert ready.human_signoff_required is True
    assert ready.authority_granted is False
    assert ready.production_or_execution_authority is False


def test_qbp4_fails_closed_when_qbp3_evidence_is_not_ready():
    service = QuantumStatisticalValidationService()
    report = service.evaluate(rows(500), candidate_p_values={"A": 0.01}, bootstrap_iterations=200)
    tampered = replace(report, state="QBP3_LOCKED_OR_REVIEW_REQUIRED")
    review = QuantumGovernanceHandoverService().evaluate(tampered)
    assert review.state == "QBP4_NOT_ELIGIBLE"
    assert "QBP3_VALIDATION_READY" in review.blockers
