from __future__ import annotations

import dataclasses

import pytest

from dvs_ai.scientific.contracts import (
    CertificationRecord,
    CertificationStatus,
    EvidenceDelta,
    EvidenceRecord,
    ExplainabilityTrace,
    RegistrySnapshot,
    RegistryStatus,
    ScientificLifecycleState,
    ValidationResult,
    ValidationStatus,
    can_transition,
    require_transition,
)


def test_evidence_record_is_immutable_and_normalizes_reasons() -> None:
    record = EvidenceRecord(
        evidence_id="ev-1",
        observed_at="2026-07-19T00:00:00Z",
        source="shadow-ledger",
        dataset_fingerprint="abc",
        sample_size=100,
        time_coverage_seconds=3600,
        quality_score=0.9,
        regimes=("TREND", "TREND"),
        reason_codes=(" data_quality_too_low ", "DATA_QUALITY_TOO_LOW"),
        metadata={"symbol": "BTCUSDT"},
    )
    assert record.regimes == ("TREND",)
    assert record.reason_codes == ("DATA_QUALITY_TOO_LOW",)
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.sample_size = 101  # type: ignore[misc]
    with pytest.raises(TypeError):
        record.metadata["symbol"] = "ETHUSDT"  # type: ignore[index]


def test_evidence_record_rejects_invalid_quality() -> None:
    with pytest.raises(ValueError, match="quality_score"):
        EvidenceRecord("ev", "now", "src", "fp", 1, 1, 1.1)


def test_meaningful_delta_cannot_bypass_hard_gates() -> None:
    with pytest.raises(ValueError, match="hard gates"):
        EvidenceDelta(
            current_evidence_id="ev-2",
            baseline_evidence_ids=("ev-1",),
            fingerprint_changed=True,
            sample_delta=100,
            time_coverage_delta_seconds=3600,
            hard_gates_passed=False,
            meaningful=True,
        )


def test_validation_metric_names_must_be_unique() -> None:
    with pytest.raises(ValueError, match="unique"):
        ValidationResult(
            validation_id="v-1",
            evidence_id="ev-1",
            started_at="a",
            completed_at="b",
            status=ValidationStatus.PASSED,
            metrics=(("sharpe", 1.0), ("sharpe", 2.0)),
        )


def test_registered_model_requires_certification() -> None:
    with pytest.raises(ValueError, match="certification_id"):
        RegistrySnapshot(
            snapshot_id="s-1",
            generated_at="now",
            model_id="m-1",
            model_version="1",
            certification_id="",
            status=RegistryStatus.REGISTERED,
            maturity_level="VALIDATED",
        )


def test_certification_and_trace_linkage() -> None:
    cert = CertificationRecord(
        certification_id="c-1",
        validation_id="v-1",
        model_id="m-1",
        model_version="1",
        evaluated_at="now",
        status=CertificationStatus.GRANTED,
    )
    trace = ExplainabilityTrace(
        trace_id="t-1",
        decision_id="d-1",
        generated_at="now",
        evidence_ids=("ev-1",),
        validation_id=cert.validation_id,
        certification_id=cert.certification_id,
        registry_snapshot_id="s-1",
    )
    assert trace.is_complete is True


def test_lifecycle_transitions_are_strict_and_fail_closed() -> None:
    assert can_transition(ScientificLifecycleState.RAW, ScientificLifecycleState.FEATURED)
    assert can_transition(ScientificLifecycleState.RAW, ScientificLifecycleState.FAILED)
    assert not can_transition(ScientificLifecycleState.RAW, ScientificLifecycleState.CERTIFIED)
    with pytest.raises(ValueError, match="RAW -> CERTIFIED"):
        require_transition(ScientificLifecycleState.RAW, ScientificLifecycleState.CERTIFIED)
