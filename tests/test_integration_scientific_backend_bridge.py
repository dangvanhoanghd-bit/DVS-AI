from __future__ import annotations

import json
from pathlib import Path

from dvs_ai.integration.models import BackendAvailability
from dvs_ai.integration.scientific_backend import ScientificBackendBridge


def _write_backend(root: Path, *, tests_successful: bool = True, enforcement: str = "FAIL_CLOSED") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "BUILD_VERIFICATION.json").write_text(
        json.dumps(
            {
                "compile": True,
                "tests_run": 432,
                "tests_successful": tests_successful,
                "cli_help_available": True,
                "build_valid": tests_successful,
            }
        ),
        encoding="utf-8",
    )
    (root / "SAFETY_BOUNDARY.json").write_text(
        json.dumps(
            {
                "testnet": "FROZEN",
                "deployment": "DISCONNECTED",
                "live": "NOT_AUTHORIZED",
                "enforcement": enforcement,
                "scope": "test",
            }
        ),
        encoding="utf-8",
    )
    (root / "BACKEND_METADATA.json").write_text(
        json.dumps({"engine_version": "2.33.0.49", "integration_mode": "TEST"}),
        encoding="utf-8",
    )


def test_verified_backend_status_is_immutable_and_observe_safe(tmp_path: Path):
    root = tmp_path / "backend"
    _write_backend(root)
    status = ScientificBackendBridge(root, app_root=tmp_path).get_status()
    assert status.availability is BackendAvailability.AVAILABLE
    assert status.display_state == "VERIFIED"
    assert status.safe_for_observation is True
    assert status.tests_run == 432
    assert status.safety.live == "NOT_AUTHORIZED"
    assert status.reason_codes == ()


def test_failed_tests_cannot_be_compensated_by_other_green_fields(tmp_path: Path):
    root = tmp_path / "backend"
    _write_backend(root, tests_successful=False)
    status = ScientificBackendBridge(root, app_root=tmp_path).get_status()
    assert status.availability is BackendAvailability.DEGRADED
    assert status.display_state == "DEGRADED"
    assert status.safe_for_observation is False
    assert "BUILD_NOT_VERIFIED" in status.reason_codes
    assert "TESTS_NOT_VERIFIED" in status.reason_codes


def test_non_fail_closed_boundary_is_degraded(tmp_path: Path):
    root = tmp_path / "backend"
    _write_backend(root, enforcement="WARN_ONLY")
    status = ScientificBackendBridge(root, app_root=tmp_path).get_status()
    assert status.display_state == "DEGRADED"
    assert "SAFETY_NOT_FAIL_CLOSED" in status.reason_codes


def test_missing_backend_returns_explainable_unavailable_status(tmp_path: Path):
    status = ScientificBackendBridge(tmp_path / "missing", app_root=tmp_path / "empty").get_status()
    assert status.availability is BackendAvailability.UNAVAILABLE
    assert status.display_state == "UNAVAILABLE"
    assert "CONFIGURED_ROOT_NOT_FOUND" in status.reason_codes
    assert "PACKAGED_SNAPSHOT_NOT_AVAILABLE" in status.reason_codes


def test_configured_root_is_reported_as_active_source(tmp_path: Path):
    from dvs_ai.integration.models import BackendSource

    root = tmp_path / "backend"
    _write_backend(root)
    status = ScientificBackendBridge(root, app_root=tmp_path / "app").get_status()
    assert status.backend_source is BackendSource.CONFIGURED_ROOT
    assert status.configured_root == str(root.resolve())
    assert status.active_root == str(root.resolve())
    assert status.fallback_reason == ""
    assert "CONFIGURED_ROOT_FALLBACK_USED" not in status.reason_codes


def test_missing_configured_root_fallback_is_visible_and_degraded(tmp_path: Path):
    from dvs_ai.integration.models import BackendSource

    configured = tmp_path / "missing-live-backend"
    snapshot = tmp_path / "app" / "scientific_backend_snapshot"
    _write_backend(snapshot)
    status = ScientificBackendBridge(configured, app_root=tmp_path / "app").get_status()
    assert status.backend_source is BackendSource.PACKAGED_SNAPSHOT
    assert status.configured_root == str(configured.resolve())
    assert status.active_root == str(snapshot.resolve())
    assert status.availability is BackendAvailability.DEGRADED
    assert status.display_state == "DEGRADED"
    assert "CONFIGURED_ROOT_NOT_FOUND" in status.reason_codes
    assert "CONFIGURED_ROOT_FALLBACK_USED" in status.reason_codes
    assert "does not exist" in status.fallback_reason


def test_configured_root_with_missing_required_file_falls_back_with_reason(tmp_path: Path):
    from dvs_ai.integration.models import BackendSource

    configured = tmp_path / "configured"
    configured.mkdir()
    (configured / "BUILD_VERIFICATION.json").write_text("{}", encoding="utf-8")
    snapshot = tmp_path / "app" / "scientific_backend_snapshot"
    _write_backend(snapshot)
    status = ScientificBackendBridge(configured, app_root=tmp_path / "app").get_status()
    assert status.backend_source is BackendSource.PACKAGED_SNAPSHOT
    assert "CONFIGURED_ROOT_STATUS_FILES_MISSING" in status.reason_codes
    assert "CONFIGURED_ROOT_FALLBACK_USED" in status.reason_codes
    assert "SAFETY_BOUNDARY.json" in status.fallback_reason


def test_configured_root_with_invalid_json_falls_back_with_reason(tmp_path: Path):
    from dvs_ai.integration.models import BackendSource

    configured = tmp_path / "configured"
    _write_backend(configured)
    (configured / "SAFETY_BOUNDARY.json").write_text("{broken", encoding="utf-8")
    snapshot = tmp_path / "app" / "scientific_backend_snapshot"
    _write_backend(snapshot)
    status = ScientificBackendBridge(configured, app_root=tmp_path / "app").get_status()
    assert status.backend_source is BackendSource.PACKAGED_SNAPSHOT
    assert "CONFIGURED_ROOT_JSON_INVALID" in status.reason_codes
    assert "CONFIGURED_ROOT_FALLBACK_USED" in status.reason_codes
    assert "Invalid JSON" in status.fallback_reason


def test_no_snapshot_after_configured_root_failure_is_unavailable(tmp_path: Path):
    from dvs_ai.integration.models import BackendSource

    configured = tmp_path / "missing"
    status = ScientificBackendBridge(configured, app_root=tmp_path / "empty").get_status()
    assert status.backend_source is BackendSource.NONE
    assert status.availability is BackendAvailability.UNAVAILABLE
    assert "CONFIGURED_ROOT_NOT_FOUND" in status.reason_codes
    assert "PACKAGED_SNAPSHOT_NOT_AVAILABLE" in status.reason_codes


def _write_scientific_artifacts(root: Path) -> None:
    (root / "VALIDATION_SUMMARY.json").write_text(json.dumps({
        "status": "VERIFIED", "last_validation_at": "2026-07-18", "validation_count": 7
    }), encoding="utf-8")
    (root / "EVIDENCE_STATUS.json").write_text(json.dumps({
        "status": "VALID", "evidence_count": 12, "last_evidence_at": "2026-07-18"
    }), encoding="utf-8")
    (root / "READINESS_SUMMARY.json").write_text(json.dumps({
        "readiness_level": "READY", "readiness_score": 91.5, "recommendation": "Continue governed validation"
    }), encoding="utf-8")
    (root / "CERTIFICATION_SUMMARY.json").write_text(json.dumps({
        "certification_status": "CERTIFIED", "certificate_id": "CERT-001", "certified_at": "2026-07-18"
    }), encoding="utf-8")


def test_scientific_summary_reads_all_optional_artifacts(tmp_path: Path):
    from dvs_ai.integration.models import ScientificDataState
    root = tmp_path / "backend"
    _write_backend(root)
    _write_scientific_artifacts(root)
    summary = ScientificBackendBridge(root, app_root=tmp_path).get_scientific_summary()
    assert summary.validation.state is ScientificDataState.VALID
    assert summary.validation.validation_count == 7
    assert summary.evidence.evidence_count == 12
    assert summary.readiness.readiness_level == "READY"
    assert summary.readiness.readiness_score == 91.5
    assert summary.certification.certification_status == "CERTIFIED"


def test_missing_scientific_artifacts_are_explicitly_unavailable(tmp_path: Path):
    from dvs_ai.integration.models import ScientificDataState
    root = tmp_path / "backend"
    _write_backend(root)
    summary = ScientificBackendBridge(root, app_root=tmp_path).get_scientific_summary()
    assert summary.validation.state is ScientificDataState.UNAVAILABLE
    assert "VALIDATION_SUMMARY_NOT_AVAILABLE" in summary.validation.reason_codes
    assert summary.evidence.state is ScientificDataState.UNAVAILABLE
    assert summary.readiness.state is ScientificDataState.UNAVAILABLE
    assert summary.certification.state is ScientificDataState.UNAVAILABLE


def test_invalid_optional_artifact_is_fail_closed_unavailable(tmp_path: Path):
    from dvs_ai.integration.models import ScientificDataState
    root = tmp_path / "backend"
    _write_backend(root)
    (root / "VALIDATION_SUMMARY.json").write_text("{broken", encoding="utf-8")
    validation = ScientificBackendBridge(root, app_root=tmp_path).get_validation_summary()
    assert validation.state is ScientificDataState.UNAVAILABLE
    assert "VALIDATION_SUMMARY_INVALID" in validation.reason_codes


def _write_explainability_artifact(root: Path, **overrides) -> None:
    payload = {
        "status": "VALID",
        "decision_id": "DEC-001",
        "generated_at": "2026-07-18T12:00:00Z",
        "decision_type": "LONG_BIAS",
        "confidence": 0.82,
        "reason_codes": ["CMF_POSITIVE", "RSI_RECOVERED"],
        "evidence_refs": ["EVID-101", "EVID-102"],
        "validation_ref": "VAL-007",
        "model_version": "2.33.0",
    }
    payload.update(overrides)
    (root / "EXPLAINABILITY_SUMMARY.json").write_text(json.dumps(payload), encoding="utf-8")


def test_explainability_summary_and_decision_trace_are_read_only_artifacts(tmp_path: Path):
    from dvs_ai.integration.models import ScientificDataState
    root = tmp_path / "backend"
    _write_backend(root)
    _write_explainability_artifact(root)
    bridge = ScientificBackendBridge(root, app_root=tmp_path)
    summary = bridge.get_explainability_summary()
    trace = bridge.get_decision_trace()
    assert summary.state is ScientificDataState.VALID
    assert summary.decision_id == "DEC-001"
    assert summary.confidence == 0.82
    assert summary.evidence_refs == ("EVID-101", "EVID-102")
    assert trace.state is ScientificDataState.VALID
    assert trace.stages == (
        "EVIDENCE:2", "VALIDATION:VAL-007", "DECISION:LONG_BIAS", "REASONS:2"
    )


def test_missing_explainability_artifact_is_explicitly_unavailable(tmp_path: Path):
    from dvs_ai.integration.models import ScientificDataState
    root = tmp_path / "backend"
    _write_backend(root)
    summary = ScientificBackendBridge(root, app_root=tmp_path).get_explainability_summary()
    assert summary.state is ScientificDataState.UNAVAILABLE
    assert "EXPLAINABILITY_SUMMARY_NOT_AVAILABLE" in summary.reason_codes


def test_invalid_explainability_artifact_is_fail_closed_unavailable(tmp_path: Path):
    from dvs_ai.integration.models import ScientificDataState
    root = tmp_path / "backend"
    _write_backend(root)
    (root / "EXPLAINABILITY_SUMMARY.json").write_text("{broken", encoding="utf-8")
    summary = ScientificBackendBridge(root, app_root=tmp_path).get_explainability_summary()
    assert summary.state is ScientificDataState.UNAVAILABLE
    assert "EXPLAINABILITY_SUMMARY_INVALID" in summary.reason_codes


def test_explainability_missing_refs_surfaces_reason_codes_without_inference(tmp_path: Path):
    root = tmp_path / "backend"
    _write_backend(root)
    _write_explainability_artifact(root, evidence_refs=[], validation_ref="", reason_codes=[])
    summary = ScientificBackendBridge(root, app_root=tmp_path).get_explainability_summary()
    assert "EXPLAINABILITY_EVIDENCE_REFS_EMPTY" in summary.reason_codes
    assert "EXPLAINABILITY_VALIDATION_REF_MISSING" in summary.reason_codes
    assert summary.evidence_refs == ()
    assert summary.validation_ref == ""


def test_scientific_summary_includes_explainability_and_trace(tmp_path: Path):
    root = tmp_path / "backend"
    _write_backend(root)
    _write_scientific_artifacts(root)
    _write_explainability_artifact(root)
    summary = ScientificBackendBridge(root, app_root=tmp_path).get_scientific_summary()
    assert summary.explainability.status == "VALID"
    assert summary.decision_trace.decision_id == "DEC-001"


def _write_model_registry(root: Path, **overrides) -> None:
    payload = {
        "registry_status": "VALID",
        "generated_at": "2026-07-18T13:00:00Z",
        "current_model": {
            "model_id": "DVS-INTRADAY",
            "version": "4.1.0",
            "training_timestamp": "2026-07-17T08:00:00Z",
            "registry_status": "CERTIFIED",
            "maturity_level": "VALIDATED",
            "certified": True,
            "certificate_id": "CERT-MODEL-041",
        },
        "models": [
            {
                "model_id": "DVS-INTRADAY",
                "version": "4.1.0",
                "training_timestamp": "2026-07-17T08:00:00Z",
                "registry_status": "CERTIFIED",
                "maturity_level": "VALIDATED",
                "certified": True,
                "certificate_id": "CERT-MODEL-041",
            },
            {
                "model_id": "DVS-INTRADAY",
                "version": "4.0.0",
                "training_timestamp": "2026-07-10T08:00:00Z",
                "registry_status": "RETIRED",
                "maturity_level": "VALIDATED",
                "certified": True,
            },
        ],
        "reason_codes": [],
    }
    payload.update(overrides)
    (root / "MODEL_REGISTRY.json").write_text(json.dumps(payload), encoding="utf-8")


def test_registry_summary_reads_current_model_and_history(tmp_path: Path):
    from dvs_ai.integration.models import ScientificDataState
    root = tmp_path / "backend"
    _write_backend(root)
    _write_model_registry(root)
    bridge = ScientificBackendBridge(root, app_root=tmp_path)
    summary = bridge.get_registry_summary()
    assert summary.state is ScientificDataState.VALID
    assert summary.registry_status == "VALID"
    assert summary.current_model is not None
    assert summary.current_model.model_id == "DVS-INTRADAY"
    assert summary.current_model.version == "4.1.0"
    assert summary.current_model.maturity_level == "VALIDATED"
    assert len(summary.model_history) == 2
    assert bridge.get_current_model() == summary.current_model
    assert bridge.get_model_history() == summary.model_history


def test_missing_registry_is_explicitly_unavailable(tmp_path: Path):
    from dvs_ai.integration.models import ScientificDataState
    root = tmp_path / "backend"
    _write_backend(root)
    summary = ScientificBackendBridge(root, app_root=tmp_path).get_registry_summary()
    assert summary.state is ScientificDataState.UNAVAILABLE
    assert "MODEL_REGISTRY_NOT_AVAILABLE" in summary.reason_codes


def test_invalid_registry_json_is_fail_closed(tmp_path: Path):
    from dvs_ai.integration.models import ScientificDataState
    root = tmp_path / "backend"
    _write_backend(root)
    (root / "MODEL_REGISTRY.json").write_text("{broken", encoding="utf-8")
    summary = ScientificBackendBridge(root, app_root=tmp_path).get_registry_summary()
    assert summary.state is ScientificDataState.UNAVAILABLE
    assert "MODEL_REGISTRY_INVALID" in summary.reason_codes


def test_registry_does_not_infer_missing_current_model(tmp_path: Path):
    root = tmp_path / "backend"
    _write_backend(root)
    _write_model_registry(root, current_model=None, current_model_id="UNKNOWN", current_model_version="9.9.9")
    summary = ScientificBackendBridge(root, app_root=tmp_path).get_registry_summary()
    assert summary.current_model is None
    assert "CURRENT_MODEL_NOT_AVAILABLE" in summary.reason_codes


def test_registry_invalid_models_shape_is_unavailable(tmp_path: Path):
    from dvs_ai.integration.models import ScientificDataState
    root = tmp_path / "backend"
    _write_backend(root)
    _write_model_registry(root, models={"unexpected": "mapping"})
    summary = ScientificBackendBridge(root, app_root=tmp_path).get_registry_summary()
    assert summary.state is ScientificDataState.UNAVAILABLE
    assert "MODEL_REGISTRY_MODELS_INVALID" in summary.reason_codes


def test_scientific_summary_includes_registry(tmp_path: Path):
    root = tmp_path / "backend"
    _write_backend(root)
    _write_scientific_artifacts(root)
    _write_explainability_artifact(root)
    _write_model_registry(root)
    summary = ScientificBackendBridge(root, app_root=tmp_path).get_scientific_summary()
    assert summary.registry.current_model is not None
    assert summary.registry.current_model.version == "4.1.0"
