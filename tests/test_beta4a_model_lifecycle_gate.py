from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from dvs_ai.beta4a.contracts import (
    EvaluationMode,
    EvaluationReport,
    FeatureSchemaIdentity,
    HoldoutConsumptionRecord,
    ModelSlotManifest,
    ModelSlotState,
    TestStatus as HoldoutTestStatus,
)
from dvs_ai.beta4a.errors import Beta4AGateError
from dvs_ai.beta4a.model_lifecycle_gate import ModelLifecycleGate


def sha(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def slot(state=ModelSlotState.TRAINED_UNVALIDATED) -> ModelSlotManifest:
    return ModelSlotManifest(
        model_slot_id="model-a",
        state=state,
        policy_identity=("scope", "scope-hash", "engine"),
        extraction_identity=("extractor", "v1"),
        feature_schema_identity=FeatureSchemaIdentity("fs-v1", "features-hash"),
        source_bundle_sha256="bundle-a",
        source_split_sha256="split-a",
    )


def qualifying_pair():
    core = {
        "report_id": "report-a",
        "model_slot_id": "model-a",
        "split_sha256": "split-a",
        "evaluation_mode": "QUALIFYING_HOLDOUT_EVALUATION",
        "qualifying": True,
        "historical_benchmark_only": False,
        "test_status_at_evaluation_start": "LOCKED_UNCONSUMED",
        "metrics": {"loss": 0.1},
    }
    consumption = HoldoutConsumptionRecord(
        split_sha256="split-a",
        model_slot_id="model-a",
        consumed_at="2026-07-23T00:00:00Z",
        evaluation_purpose="QUALIFYING_HOLDOUT_EVALUATION",
        evaluation_report_sha256=sha(core),
    )
    consumption_payload = {
        "split_sha256": consumption.split_sha256,
        "model_slot_id": consumption.model_slot_id,
        "consumed_at": consumption.consumed_at,
        "evaluation_purpose": consumption.evaluation_purpose,
        "evaluation_report_sha256": consumption.evaluation_report_sha256,
    }
    record_sha = sha(consumption_payload)
    report = EvaluationReport(
        report_id="report-a",
        model_slot_id="model-a",
        split_sha256="split-a",
        evaluation_mode=EvaluationMode.QUALIFYING_HOLDOUT_EVALUATION,
        qualifying=True,
        historical_benchmark_only=False,
        test_status_at_evaluation_start=HoldoutTestStatus.LOCKED_UNCONSUMED,
        holdout_consumption_record_sha256=record_sha,
        metrics={"loss": 0.1},
    )
    return report, consumption, record_sha


def make_gate(tmp_path, records):
    return ModelLifecycleGate(
        state_db_path=tmp_path / "lifecycle.sqlite3",
        consumption_record_loader=records.get,
    )


def test_qualifying_report_promotes_and_seals_transition(tmp_path):
    report, consumption, record_sha = qualifying_pair()
    gate = make_gate(tmp_path, {record_sha: consumption})
    promoted = gate.promote_to_validated(model_slot=slot(), evaluation_report=report)
    assert promoted.state is ModelSlotState.VALIDATED
    audit = gate.audit_snapshot("model-a")
    assert [row["state"] for row in audit["manifests"]] == ["TRAINED_UNVALIDATED", "VALIDATED"]
    assert len(audit["transitions"]) == 1
    transition = audit["transitions"][0]
    assert transition["source_state"] == "TRAINED_UNVALIDATED"
    assert transition["target_state"] == "VALIDATED"
    assert transition["holdout_consumption_record_sha256"] == record_sha


def test_historical_report_is_hard_blocked(tmp_path):
    report = EvaluationReport(
        report_id="historical",
        model_slot_id="model-a",
        split_sha256="split-a",
        evaluation_mode=EvaluationMode.HISTORICAL_BENCHMARK_EVALUATION,
        qualifying=False,
        historical_benchmark_only=True,
        test_status_at_evaluation_start=HoldoutTestStatus.CONSUMED,
        holdout_consumption_record_sha256=None,
        metrics={"loss": 0.2},
    )
    gate = make_gate(tmp_path, {})
    with pytest.raises(Beta4AGateError) as exc:
        gate.promote_to_validated(model_slot=slot(), evaluation_report=report)
    assert exc.value.code == "VALIDATION_SOURCE_TEST_ALREADY_CONSUMED"


def test_only_trained_unvalidated_can_promote(tmp_path):
    report, consumption, record_sha = qualifying_pair()
    gate = make_gate(tmp_path, {record_sha: consumption})
    with pytest.raises(Beta4AGateError) as exc:
        gate.promote_to_validated(model_slot=slot(ModelSlotState.TRAINING), evaluation_report=report)
    assert exc.value.code == "MODEL_SLOT_TRANSITION_NOT_ALLOWED"


def test_report_must_belong_to_same_model_slot_and_split(tmp_path):
    report, consumption, record_sha = qualifying_pair()
    gate = make_gate(tmp_path, {record_sha: consumption})
    with pytest.raises(Beta4AGateError) as exc:
        gate.promote_to_validated(
            model_slot=replace(slot(), model_slot_id="other"), evaluation_report=report
        )
    assert exc.value.code == "MODEL_SLOT_EVALUATION_BINDING_MISMATCH"

    with pytest.raises(Beta4AGateError) as exc:
        gate.promote_to_validated(
            model_slot=replace(slot(), source_split_sha256="other-split"),
            evaluation_report=report,
        )
    assert exc.value.code == "MODEL_SLOT_SPLIT_BINDING_MISMATCH"


def test_consumption_record_must_exist_and_match_hash(tmp_path):
    report, consumption, record_sha = qualifying_pair()
    missing_gate = make_gate(tmp_path, {})
    with pytest.raises(Beta4AGateError) as exc:
        missing_gate.promote_to_validated(model_slot=slot(), evaluation_report=report)
    assert exc.value.code == "HOLDOUT_CONSUMPTION_RECORD_NOT_FOUND"

    tampered = replace(consumption, consumed_at="2026-07-24T00:00:00Z")
    tampered_gate = ModelLifecycleGate(
        state_db_path=tmp_path / "tampered.sqlite3",
        consumption_record_loader={record_sha: tampered}.get,
    )
    with pytest.raises(Beta4AGateError) as exc:
        tampered_gate.promote_to_validated(model_slot=slot(), evaluation_report=report)
    assert exc.value.code == "HOLDOUT_CONSUMPTION_RECORD_HASH_MISMATCH"


def test_consumption_record_must_bind_to_report_core(tmp_path):
    report, consumption, record_sha = qualifying_pair()
    wrong = replace(consumption, evaluation_report_sha256="0" * 64)
    wrong_sha = sha({
        "split_sha256": wrong.split_sha256,
        "model_slot_id": wrong.model_slot_id,
        "consumed_at": wrong.consumed_at,
        "evaluation_purpose": wrong.evaluation_purpose,
        "evaluation_report_sha256": wrong.evaluation_report_sha256,
    })
    report = replace(report, holdout_consumption_record_sha256=wrong_sha)
    gate = make_gate(tmp_path, {wrong_sha: wrong})
    with pytest.raises(Beta4AGateError) as exc:
        gate.promote_to_validated(model_slot=slot(), evaluation_report=report)
    assert exc.value.code == "EVALUATION_REPORT_HASH_MISMATCH"


def test_second_validated_transition_is_refused(tmp_path):
    report, consumption, record_sha = qualifying_pair()
    gate = make_gate(tmp_path, {record_sha: consumption})
    gate.promote_to_validated(model_slot=slot(), evaluation_report=report)
    with pytest.raises(Beta4AGateError) as exc:
        gate.promote_to_validated(model_slot=slot(), evaluation_report=report)
    assert exc.value.code == "MODEL_SLOT_ALREADY_VALIDATED"
