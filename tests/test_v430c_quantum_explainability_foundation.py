from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dvs_ai.services.quantum_explainability import (
    ExplanationState,
    QuantumExplainabilityFoundation,
    verify_explanation_bundle,
)
from dvs_ai.services.quantum_explainability.foundation import canonical_json


def make_dataset(tmp_path: Path, *, with_evidence: bool = False):
    row = {
        "sample_id": "QDS-1",
        "setup_episode_id": "episode-1",
        "candidate_id": "candidate-1",
        "activation_evaluation_id": "eval-1",
        "first_evaluation_id": "eval-1",
        "first_eligible_timestamp": "2026-01-01T00:00:00+00:00",
        "symbol": "BTC/USDT",
        "direction": "LONG",
        "lifecycle_family": "RETEST",
        "cohort": "CENSUS",
        "decision_engine_checksum": "engine-hash",
        "trade_plan_profile_hash": "plan-hash",
        "policy_scope_id": "QPS-1",
        "policy_scope_hash": "scope-hash",
        "outcome_status": "WIN",
        "realized_r": 4.0,
        "mfe_r": 8.0,
        "mae_r": -0.2,
        "outcome_time": "2026-01-02T00:00:00+00:00",
        "market_event_cluster_id": "cluster",
        "symbol_cluster": "BTC/USDT",
        "source_row_hash": "source-hash",
    }
    if with_evidence:
        row.update({"cmf": 0.22, "rsi": 51.0})
    ds = tmp_path / "quantum_research_dataset.jsonl"
    ds.write_text(json.dumps(row) + "\n", encoding="utf-8")
    ds_hash = hashlib.sha256(ds.read_bytes()).hexdigest()
    manifest = {
        "manifest_version": "dvs-quantum-dataset-manifest-v1",
        "dataset_schema_version": "dvs-quantum-dataset-v1",
        "dataset_file": ds.name,
        "dataset_sha256": ds_hash,
        "readiness_state": "UNOBSERVABLE",
        "integrity_findings": [{"code": "QG01", "passed": True, "detail": "ok", "count": 0}],
    }
    manifest["self_sha256"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    mf = tmp_path / "quantum_research_dataset.manifest.json"
    mf.write_text(json.dumps(manifest), encoding="utf-8")
    return ds, mf


def test_builds_trace_without_using_outcome_as_evidence(tmp_path):
    ds, mf = make_dataset(tmp_path, with_evidence=True)
    result = QuantumExplainabilityFoundation(ds, mf, expected_evidence_fields=("cmf", "rsi")).build()
    assert result.state == ExplanationState.VERIFIED
    record = result.records[0]
    names = {x.name for x in record.observed_evidence}
    assert names == {"cmf", "rsi"}
    assert "outcome_status" not in names and "realized_r" not in names and "mfe_r" not in names
    assert all("WIN" not in node.label for node in record.graph_nodes)
    assert not result.optimizer_allowed and not result.recommendation_allowed
    assert not result.shadow_apply_allowed and not result.main_write_authority


def test_missing_snapshot_evidence_is_explicit_not_invented(tmp_path):
    ds, mf = make_dataset(tmp_path)
    result = QuantumExplainabilityFoundation(ds, mf, expected_evidence_fields=("cmf", "rsi", "oi")).build()
    assert result.state == ExplanationState.INCOMPLETE_EVIDENCE
    assert result.records[0].observed_evidence == ()
    assert result.records[0].missing_evidence == ("cmf", "rsi", "oi")
    assert any("absent" in x for x in result.records[0].limitations)


def test_rejects_outcome_field_configured_as_evidence(tmp_path):
    ds, mf = make_dataset(tmp_path)
    with pytest.raises(ValueError):
        QuantumExplainabilityFoundation(ds, mf, expected_evidence_fields=("rsi", "realized_r"))


def test_tampered_dataset_is_blocked(tmp_path):
    ds, mf = make_dataset(tmp_path)
    ds.write_text(ds.read_text() + "{}\n", encoding="utf-8")
    result = QuantumExplainabilityFoundation(ds, mf).build()
    assert result.state == ExplanationState.DATASET_INTEGRITY_BLOCKED
    assert not result.dataset_integrity_verified and not result.records


def test_export_is_self_sealed_and_independently_verified(tmp_path):
    ds, mf = make_dataset(tmp_path, with_evidence=True)
    result = QuantumExplainabilityFoundation(ds, mf, expected_evidence_fields=("cmf", "rsi")).build()
    records, manifest = result.export(tmp_path / "out")
    ok, detail = verify_explanation_bundle(records, manifest)
    assert ok, detail
    records.write_text(records.read_text() + " ", encoding="utf-8")
    ok, detail = verify_explanation_bundle(records, manifest)
    assert not ok and "checksum" in detail


def test_explanation_is_deterministic_for_same_sealed_dataset(tmp_path):
    ds, mf = make_dataset(tmp_path, with_evidence=True)
    a = QuantumExplainabilityFoundation(ds, mf, expected_evidence_fields=("cmf", "rsi")).build().records[0]
    b = QuantumExplainabilityFoundation(ds, mf, expected_evidence_fields=("cmf", "rsi")).build().records[0]
    assert a.explanation_id == b.explanation_id
    assert a.record_sha256 == b.record_sha256
    assert a.graph_nodes == b.graph_nodes and a.graph_edges == b.graph_edges
