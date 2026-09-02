from dataclasses import replace

from dvs_ai.scientific.contracts import (
    CertificationRecord, CertificationStatus, EvidenceDelta, EvidenceRecord,
    RegistrySnapshot, RegistryStatus, ScientificLifecycleState, StabilityStatus,
    ValidationResult, ValidationStatus,
)
from dvs_ai.scientific.pipeline import ScientificLifecyclePipeline


def evidence():
    return EvidenceRecord("e1", "2026-07-19T00:00:00Z", "test", "fp2", 200, 7200, 0.95, ("trend",), ("long",))


def delta_stage(e):
    return EvidenceDelta(e.evidence_id, ("e0",), True, 100, 3600, ("trend",), ("long",), 0.1, True, True)


def validation_stage(e, d):
    return ValidationResult("v1", e.evidence_id, "start", "end", ValidationStatus.PASSED)


def stability_stage(v):
    return replace(v, stability_status=StabilityStatus.STABLE)


def certification_stage(v):
    return CertificationRecord("c1", v.validation_id, "m1", "1", "now", CertificationStatus.GRANTED)


def registry_stage(c):
    return RegistrySnapshot("r1", "now", c.model_id, c.model_version, c.certification_id, RegistryStatus.REGISTERED, "SCIENTIFIC")


def pipeline(**overrides):
    stages = dict(delta_stage=delta_stage, validation_stage=validation_stage, stability_stage=stability_stage,
                  certification_stage=certification_stage, registry_stage=registry_stage)
    stages.update(overrides)
    return ScientificLifecyclePipeline(**stages)


def test_happy_path_reaches_available_and_preserves_artifacts():
    result = pipeline().run(evidence(), run_id="run-1")
    assert result.succeeded
    assert result.state is ScientificLifecycleState.AVAILABLE
    assert result.registry_snapshot.snapshot_id == "r1"
    assert [e.state for e in result.events][-3:] == [ScientificLifecycleState.CERTIFIED, ScientificLifecycleState.REGISTERED, ScientificLifecycleState.AVAILABLE]


def test_non_meaningful_delta_fails_closed_before_validation():
    called = {"validation": False}
    def weak(e): return replace(delta_stage(e), meaningful=False, reason_codes=("EVIDENCE_DELTA_TOO_SMALL",))
    def should_not_run(e, d): called["validation"] = True; return validation_stage(e, d)
    result = pipeline(delta_stage=weak, validation_stage=should_not_run).run(evidence())
    assert result.state is ScientificLifecycleState.FAILED
    assert not called["validation"]
    assert result.reason_codes == ("EVIDENCE_DELTA_TOO_SMALL",)


def test_validation_failure_stops_later_stages():
    def failed(e, d): return replace(validation_stage(e, d), status=ValidationStatus.FAILED, reason_codes=("VALIDATION_FAILED",))
    result = pipeline(validation_stage=failed).run(evidence())
    assert result.state is ScientificLifecycleState.FAILED
    assert result.validation.status is ValidationStatus.FAILED
    assert result.certification is None


def test_unstable_validation_cannot_be_certified():
    def unstable(v): return replace(v, stability_status=StabilityStatus.UNSTABLE, reason_codes=("STABILITY_FAILED",))
    result = pipeline(stability_stage=unstable).run(evidence())
    assert result.state is ScientificLifecycleState.FAILED
    assert result.certification is None


def test_denied_certification_cannot_reach_registry():
    def denied(v): return replace(certification_stage(v), status=CertificationStatus.DENIED, reason_codes=("CERTIFICATION_NOT_GRANTED",))
    result = pipeline(certification_stage=denied).run(evidence())
    assert result.state is ScientificLifecycleState.FAILED
    assert result.registry_snapshot is None


def test_unregistered_snapshot_is_not_available():
    def unavailable(c): return replace(registry_stage(c), status=RegistryStatus.NOT_REGISTERED, certification_id="", reason_codes=("REGISTRY_NOT_AVAILABLE",))
    result = pipeline(registry_stage=unavailable).run(evidence())
    assert result.state is ScientificLifecycleState.FAILED
    assert not result.succeeded


def test_stage_exception_is_contained_and_reported():
    def boom(e): raise RuntimeError("boom")
    result = pipeline(delta_stage=boom).run(evidence())
    assert result.state is ScientificLifecycleState.FAILED
    assert result.reason_codes == ("PIPELINE_STAGE_EXCEPTION:RUNTIMEERROR",)
