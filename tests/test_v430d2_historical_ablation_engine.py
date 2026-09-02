from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dvs_ai.services.quantum_counterfactual import (
    AblationState,
    AblationStudy,
    AssociationClass,
    HistoricalAblationEngine,
    verify_ablation_bundle,
)
from dvs_ai.services.quantum_explainability.foundation import canonical_json


def make_dataset(tmp_path: Path, rows=None):
    rows = rows or [
        {
            "sample_id": "QDS-1", "setup_episode_id": "episode-1", "candidate_id": "candidate-1",
            "activation_evaluation_id": "eval-1", "first_evaluation_id": "eval-1",
            "first_eligible_timestamp": "2026-01-01T00:00:00+00:00", "policy_scope_id": "QPS-1",
            "policy_scope_hash": "scope-hash", "decision_engine_checksum": "engine-hash",
            "trade_plan_profile_hash": "plan-hash", "source_row_hash": "source-hash-1",
            "cmf": 0.2, "rsi": 52.0, "outcome_status": "WIN", "realized_r": 2.0,
        },
        {
            "sample_id": "QDS-2", "setup_episode_id": "episode-2", "candidate_id": "candidate-2",
            "activation_evaluation_id": "eval-2", "first_evaluation_id": "eval-2",
            "first_eligible_timestamp": "2026-01-02T00:00:00+00:00", "policy_scope_id": "QPS-1",
            "policy_scope_hash": "scope-hash", "decision_engine_checksum": "engine-hash",
            "trade_plan_profile_hash": "plan-hash", "source_row_hash": "source-hash-2",
            "cmf": None, "rsi": 48.0, "outcome_status": "LOSS", "realized_r": -1.0,
        },
    ]
    ds = tmp_path / "quantum_research_dataset.jsonl"
    ds.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    manifest = {
        "manifest_version": "dvs-quantum-dataset-manifest-v1",
        "dataset_schema_version": "dvs-quantum-dataset-v1",
        "dataset_file": ds.name,
        "dataset_sha256": hashlib.sha256(ds.read_bytes()).hexdigest(),
        "readiness_state": "UNOBSERVABLE",
        "integrity_findings": [{"code": "QG01", "passed": True, "detail": "ok", "count": 0}],
    }
    manifest["self_sha256"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    mf = tmp_path / "quantum_research_dataset.manifest.json"
    mf.write_text(json.dumps(manifest), encoding="utf-8")
    return ds, mf


def test_ablation_is_non_identifiable_and_does_not_change_outcomes(tmp_path):
    ds, mf = make_dataset(tmp_path)
    result = HistoricalAblationEngine(ds, mf).run(AblationStudy("study-cmf", "cmf", "Remove CMF"))
    assert result.state == AblationState.COMPLETED_NON_IDENTIFIABLE
    assert result.association_class == AssociationClass.INCONCLUSIVE
    assert result.target_observed_n == 1 and result.target_missing_n == 1
    assert result.baseline == result.projected_without_target
    assert result.delta_mean_realized_r == 0.0
    assert not result.optimizer_allowed and not result.recommendation_allowed
    assert not result.shadow_apply_allowed and not result.main_write_authority


def test_outcome_field_cannot_be_ablation_target(tmp_path):
    ds, mf = make_dataset(tmp_path)
    result = HistoricalAblationEngine(ds, mf).run(AblationStudy("study-r", "realized_r"))
    assert result.state == AblationState.INVALID_STUDY
    assert "OUTCOME_OR_FUTURE_FIELD_CANNOT_BE_ABLATED_AS_EVIDENCE" in result.violations


def test_governed_identity_field_cannot_be_ablation_target(tmp_path):
    ds, mf = make_dataset(tmp_path)
    result = HistoricalAblationEngine(ds, mf).run(AblationStudy("study-policy", "policy_scope_hash"))
    assert result.state == AblationState.INVALID_STUDY
    assert "GOVERNED_IDENTITY_FIELD_CANNOT_BE_ABLATED" in result.violations


def test_invalid_replay_blocks_ablation(tmp_path):
    rows = [{
        "sample_id": "QDS-1", "setup_episode_id": "episode-1", "candidate_id": "candidate-1",
        "activation_evaluation_id": "eval-later", "first_evaluation_id": "eval-original",
        "first_eligible_timestamp": "2026-01-01T00:00:00+00:00", "policy_scope_id": "QPS-1",
        "policy_scope_hash": "scope-hash", "decision_engine_checksum": "engine-hash",
        "trade_plan_profile_hash": "plan-hash", "source_row_hash": "source-hash", "cmf": 0.2,
        "outcome_status": "WIN", "realized_r": 1.0,
    }]
    ds, mf = make_dataset(tmp_path, rows)
    result = HistoricalAblationEngine(ds, mf).run(AblationStudy("study-cmf", "cmf"))
    assert result.state == AblationState.REPLAY_BLOCKED


def test_tampered_dataset_blocks_ablation(tmp_path):
    ds, mf = make_dataset(tmp_path)
    ds.write_text(ds.read_text() + "{}\n", encoding="utf-8")
    result = HistoricalAblationEngine(ds, mf).run(AblationStudy("study-cmf", "cmf"))
    assert result.state == AblationState.DATASET_INTEGRITY_BLOCKED


def test_export_bundle_is_self_sealed(tmp_path):
    ds, mf = make_dataset(tmp_path)
    result = HistoricalAblationEngine(ds, mf).run(AblationStudy("study-cmf", "cmf"))
    result_path, manifest_path = result.export(tmp_path / "out")
    ok, detail = verify_ablation_bundle(result_path, manifest_path)
    assert ok, detail
    result_path.write_text(result_path.read_text() + " ", encoding="utf-8")
    ok, detail = verify_ablation_bundle(result_path, manifest_path)
    assert not ok and "checksum" in detail
