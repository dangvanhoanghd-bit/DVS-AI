from __future__ import annotations

from dataclasses import replace

import pytest

from dvs_ai.beta4a.bundle_selection_gate import BundleSelectionGate
from dvs_ai.beta4a.contracts import (
    EvaluationMode,
    EvaluationReport,
    FeatureColumn,
    FeatureSchemaManifest,
    TestStatus as HoldoutTestStatus,
)
from dvs_ai.beta4a.errors import Beta4AGateError
from dvs_ai.beta4a.model_evaluation_gate import ModelEvaluationGate
from dvs_ai.services.beta3_cross_bundle import RegistryEntry


def entry(sha: str, **overrides) -> RegistryEntry:
    values = dict(
        bundle_path=f"/{sha}", dataset_id=f"d-{sha}", bundle_sha256=sha,
        parent_bundle_sha256=None, build_timestamp="2026-07-23T00:00:00Z",
        decision_engine_checksum="engine-a", policy_scope_id="policy-a",
        policy_scope_hash="scope-a", extractor_checksum="extractor-a",
        extractor_schema_version="v1", burn_in_level="RESEARCH_CANDIDATE_ONLY",
        record_count=100, coverage_ratio=0.9, beta3b_quality_score=0.8,
    )
    values.update(overrides)
    return RegistryEntry(**values)


def test_feature_schema_identity_is_order_sensitive_and_deterministic():
    first = FeatureSchemaManifest("v1", (
        FeatureColumn("rsi", "float64", "raw", 0),
        FeatureColumn("cmf", "float64", "raw", 1),
    ))
    repeated = FeatureSchemaManifest("v1", first.columns)
    reversed_schema = FeatureSchemaManifest("v1", (
        FeatureColumn("cmf", "float64", "raw", 0),
        FeatureColumn("rsi", "float64", "raw", 1),
    ))
    assert first.identity == repeated.identity
    assert first.identity != reversed_schema.identity
    assert first.ordered_names() == ("rsi", "cmf")


def test_feature_schema_rejects_non_contiguous_column_order():
    with pytest.raises(ValueError, match="contiguous"):
        FeatureSchemaManifest("v1", (FeatureColumn("rsi", "float64", "raw", 1),))


def test_qualifying_report_requires_consumption_record_and_unconsumed_start():
    report = EvaluationReport(
        report_id="r1", model_slot_id="m1", split_sha256="s1",
        evaluation_mode=EvaluationMode.QUALIFYING_HOLDOUT_EVALUATION,
        qualifying=True, historical_benchmark_only=False,
        test_status_at_evaluation_start=HoldoutTestStatus.LOCKED_UNCONSUMED,
        holdout_consumption_record_sha256="c1", metrics={"loss": 0.2},
    )
    assert report.qualifying
    with pytest.raises(ValueError, match="contradict"):
        replace(report, holdout_consumption_record_sha256=None)


def test_historical_report_is_structurally_non_qualifying():
    report = EvaluationReport(
        report_id="r2", model_slot_id="m2", split_sha256="s1",
        evaluation_mode=EvaluationMode.HISTORICAL_BENCHMARK_EVALUATION,
        qualifying=False, historical_benchmark_only=True,
        test_status_at_evaluation_start=HoldoutTestStatus.CONSUMED,
        holdout_consumption_record_sha256=None, metrics={"loss": 0.3},
    )
    assert report.historical_benchmark_only


def test_bundle_selection_gate_reuses_beta3_promotion_and_selects_one_bundle():
    selection = BundleSelectionGate().select([entry("a"), entry("b", record_count=101)])
    assert selection.recommendation == "TRAINING_CANDIDATE"
    assert selection.bundle_sha256 == "b"


def test_bundle_selection_gate_blocks_ambiguous_or_absent_training_candidate():
    with pytest.raises(Beta4AGateError) as exc:
        BundleSelectionGate().select([entry("a")])
    assert exc.value.code == "TRAINING_CANDIDATE_CARDINALITY_VIOLATION"


def test_model_evaluation_gate_requires_explicit_runtime_dependencies(tmp_path):
    gate = ModelEvaluationGate(
        state_db_path=tmp_path / "holdout.sqlite3",
        test_row_loader=lambda _split: [],
    )
    report = gate.evaluate(
        model_slot_id="m", split_sha256="s", evaluator=lambda *_: {"loss": 0.0}
    )
    assert report.qualifying
