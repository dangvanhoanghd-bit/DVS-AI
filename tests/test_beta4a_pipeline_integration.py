from __future__ import annotations

import json
import sqlite3

import pytest

from dvs_ai.beta4a.contracts import FeatureColumn, FeatureSchemaManifest, HoldoutConsumptionRecord, ModelSlotState
from dvs_ai.beta4a.dataset_split import DatasetRowRecord
from dvs_ai.beta4a.errors import Beta4AGateError
from dvs_ai.beta4a.feature_schema import FeatureMatrixSourceRow
from dvs_ai.beta4a.leakage_detector import LeakageRowEvidence
from dvs_ai.beta4a.model_evaluation_gate import ModelEvaluationGate
from dvs_ai.beta4a.model_lifecycle_gate import ModelLifecycleGate
from dvs_ai.beta4a.model_registry import ModelRegistry
from dvs_ai.beta4a.pipeline import Beta4APipeline
from dvs_ai.services.beta3_cross_bundle import RegistryEntry


def entry(*, sha="bundle-a", parent=None, quality=1.0, timestamp="2026-07-23T00:00:00Z") -> RegistryEntry:
    return RegistryEntry(
        bundle_path=f"{sha}.zip", dataset_id=f"dataset-{sha}", bundle_sha256=sha,
        parent_bundle_sha256=parent, build_timestamp=timestamp,
        decision_engine_checksum="engine", policy_scope_id="scope", policy_scope_hash="scope-hash",
        extractor_checksum="extractor", extractor_schema_version="v1",
        burn_in_level="BURN_IN_COMPLETE", record_count=1000, coverage_ratio=1.0,
        beta3b_quality_score=quality,
    )


def schema() -> FeatureSchemaManifest:
    return FeatureSchemaManifest("fs-v1", (FeatureColumn("rsi", "float64", "numeric", 0),))


def rows():
    dataset = []
    leakage = []
    features = []
    for i in range(12):
        row_id = f"r{i:02d}"
        day = i + 1
        dataset.append(DatasetRowRecord(row_id, f"2026-01-{day:02d}T10:00:00Z", f"2026-01-{day:02d}T12:00:00Z", f"g{i:02d}"))
        leakage.append(LeakageRowEvidence(row_id, f"g{i:02d}", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", i % 2, {"rsi": (i * 7) % 5}))
        features.append(FeatureMatrixSourceRow(row_id, {"rsi": 40.0 + i}, i % 2))
    return dataset, leakage, features


def consumption_loader(db_path):
    def load(record_sha256: str):
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT payload_json FROM holdout_consumption_records WHERE record_sha256=?", (record_sha256,)).fetchone()
        return HoldoutConsumptionRecord(**json.loads(row["payload_json"])) if row else None
    return load


def make_pipeline(tmp_path):
    evaluation_db = tmp_path / "evaluation.sqlite3"
    evaluation = ModelEvaluationGate(state_db_path=evaluation_db, test_row_loader=lambda split_sha: ("locked-test", split_sha))
    lifecycle = ModelLifecycleGate(state_db_path=tmp_path / "lifecycle.sqlite3", consumption_record_loader=consumption_loader(evaluation_db))
    registry = ModelRegistry(state_db_path=tmp_path / "registry.sqlite3")
    return Beta4APipeline(model_registry=registry, evaluation_gate=evaluation, lifecycle_gate=lifecycle), registry


def test_end_to_end_bundle_to_validated(tmp_path):
    pipeline, registry = make_pipeline(tmp_path)
    dataset, leakage, features = rows()
    trained = []
    result = pipeline.run(
        registry_entries=[entry(sha="bundle-old", quality=0.8, timestamp="2026-07-22T00:00:00Z"), entry(sha="bundle-a", parent="bundle-old", quality=1.0)], dataset_rows=dataset, leakage_rows=leakage,
        feature_rows=features, feature_schema=schema(), model_slot_id="model-a",
        trainer=lambda slot, matrix: (trained.append((slot, matrix.matrix_sha256)) or b"model-a"),
        evaluator=lambda slot, test_rows: {"loss": 0.1},
    )
    assert trained and result.validated_manifest.state is ModelSlotState.VALIDATED
    assert result.leakage_report.status.value == "PASS"
    assert registry.get_current("model-a").state is ModelSlotState.TRAINED_UNVALIDATED


def test_leakage_hard_block_occurs_before_model_slot_creation(tmp_path):
    pipeline, registry = make_pipeline(tmp_path)
    dataset, leakage, features = rows()
    leakage[0] = LeakageRowEvidence("r00", "g00", "2026-02-01T00:00:00Z", "2026-01-02T00:00:00Z", 0, {"rsi": 1})
    with pytest.raises(Beta4AGateError) as exc:
        pipeline.run(
            registry_entries=[entry(sha="bundle-old", quality=0.8, timestamp="2026-07-22T00:00:00Z"), entry(sha="bundle-a", parent="bundle-old", quality=1.0)], dataset_rows=dataset, leakage_rows=leakage,
            feature_rows=features, feature_schema=schema(), model_slot_id="model-b",
            trainer=lambda slot, matrix: b"model-b", evaluator=lambda slot, test_rows: {"loss": 0.2},
        )
    assert exc.value.code in {"LEAKAGE_REPORT_HARD_BLOCKED"}
    assert registry.get_current("model-b") is None


def test_trainer_boundary_has_no_test_partition(tmp_path):
    pipeline, _ = make_pipeline(tmp_path)
    dataset, leakage, features = rows()
    observed = {}

    def trainer(slot, matrix):
        observed["has_test"] = hasattr(matrix, "test")
        observed["train_rows"] = len(matrix.train.dataset_row_ids)
        return b"sealed-model"

    pipeline.run(
        registry_entries=[entry(sha="bundle-old", quality=0.8, timestamp="2026-07-22T00:00:00Z"), entry(sha="bundle-a", parent="bundle-old", quality=1.0)],
        dataset_rows=dataset, leakage_rows=leakage, feature_rows=features,
        feature_schema=schema(), model_slot_id="model-isolated", trainer=trainer,
        evaluator=lambda slot, test_rows: {"loss": 0.1},
    )
    assert observed == {"has_test": False, "train_rows": observed["train_rows"]}
    assert observed["train_rows"] > 0


def test_pipeline_binds_model_matrix_and_training_run(tmp_path):
    pipeline, _ = make_pipeline(tmp_path)
    dataset, leakage, features = rows()
    result = pipeline.run(
        registry_entries=[entry(sha="bundle-old", quality=0.8, timestamp="2026-07-22T00:00:00Z"), entry(sha="bundle-a", parent="bundle-old", quality=1.0)],
        dataset_rows=dataset, leakage_rows=leakage, feature_rows=features,
        feature_schema=schema(), model_slot_id="model-bound", trainer=lambda slot, matrix: b"model-bound-bytes",
        evaluator=lambda slot, test_rows: {"loss": 0.1},
    )
    assert result.feature_matrix.test.dataset_row_ids == ()
    assert result.feature_matrix.test.values == ()
    assert result.feature_matrix.test.labels == ()
    assert result.trained_manifest.model_artifact_sha256 == result.trained_model_artifact.model_artifact_sha256
    assert result.trained_manifest.feature_matrix_sha256 == result.feature_matrix.matrix_sha256
    assert result.validated_manifest.training_run_id == result.trained_model_artifact.training_run_id
