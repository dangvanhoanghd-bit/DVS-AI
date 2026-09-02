from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dvs_ai.services.quantum_counterfactual import HistoricalReplayEngine, ReplayState, verify_replay_bundle
from dvs_ai.services.quantum_explainability.foundation import canonical_json


def make_dataset(tmp_path: Path, **overrides):
    row = {
        "sample_id": "QDS-1",
        "setup_episode_id": "episode-1",
        "candidate_id": "candidate-1",
        "activation_evaluation_id": "eval-1",
        "first_evaluation_id": "eval-1",
        "first_eligible_timestamp": "2026-01-01T00:00:00+00:00",
        "symbol": "BTC/USDT",
        "direction": "LONG",
        "policy_scope_id": "QPS-1",
        "policy_scope_hash": "scope-hash",
        "decision_engine_checksum": "engine-hash",
        "trade_plan_profile_hash": "plan-hash",
        "source_row_hash": "source-hash",
        "cmf": 0.2,
        "rsi": 52.0,
        "outcome_status": "WIN",
        "realized_r": 2.0,
        "outcome_time": "2026-01-02T00:00:00+00:00",
    }
    row.update(overrides)
    ds = tmp_path / "quantum_research_dataset.jsonl"
    ds.write_text(json.dumps(row) + "\n", encoding="utf-8")
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


def test_valid_first_eligible_replay_is_verified(tmp_path):
    ds, mf = make_dataset(tmp_path)
    result = HistoricalReplayEngine(ds, mf).build()
    assert result.state == ReplayState.VERIFIED
    assert result.verified_count == 1 and result.invalid_count == 0
    record = result.records[0]
    assert record.replay_basis == "FIRST_ELIGIBLE_PLAN"
    assert "cmf" in record.snapshot_fields and "rsi" in record.snapshot_fields
    assert "outcome_status" not in record.snapshot_fields
    assert "realized_r" not in record.snapshot_fields
    assert not result.optimizer_allowed and not result.recommendation_allowed
    assert not result.shadow_apply_allowed and not result.main_write_authority


def test_first_eligible_evaluation_mismatch_is_invalid(tmp_path):
    ds, mf = make_dataset(tmp_path, first_evaluation_id="eval-original", activation_evaluation_id="eval-later")
    result = HistoricalReplayEngine(ds, mf).build()
    assert result.state == ReplayState.INVALID_REPLAY
    assert "FIRST_ELIGIBLE_EVALUATION_MISMATCH" in result.records[0].violations


def test_missing_policy_identity_is_invalid(tmp_path):
    ds, mf = make_dataset(tmp_path, policy_scope_hash="")
    result = HistoricalReplayEngine(ds, mf).build()
    assert result.state == ReplayState.INVALID_REPLAY
    assert "MISSING_POLICY_SCOPE_HASH" in result.records[0].violations


def test_naive_timestamp_is_invalid(tmp_path):
    ds, mf = make_dataset(tmp_path, first_eligible_timestamp="2026-01-01T00:00:00")
    result = HistoricalReplayEngine(ds, mf).build()
    assert result.state == ReplayState.INVALID_REPLAY
    assert "INVALID_FIRST_ELIGIBLE_TIMESTAMP" in result.records[0].violations


def test_tampered_dataset_is_integrity_blocked(tmp_path):
    ds, mf = make_dataset(tmp_path)
    ds.write_text(ds.read_text() + "{}\n", encoding="utf-8")
    result = HistoricalReplayEngine(ds, mf).build()
    assert result.state == ReplayState.DATASET_INTEGRITY_BLOCKED
    assert not result.dataset_integrity_verified and not result.records


def test_export_bundle_is_self_sealed_and_verifiable(tmp_path):
    ds, mf = make_dataset(tmp_path)
    result = HistoricalReplayEngine(ds, mf).build()
    records, manifest = result.export(tmp_path / "out")
    ok, detail = verify_replay_bundle(records, manifest)
    assert ok, detail
    records.write_text(records.read_text() + " ", encoding="utf-8")
    ok, detail = verify_replay_bundle(records, manifest)
    assert not ok and "checksum" in detail
