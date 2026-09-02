from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dvs_ai.services.quantum_counterfactual import (
    AblationStudy,
    AssociationClass,
    UncertaintyEstimator,
    UncertaintyState,
    verify_uncertainty_bundle,
)
from dvs_ai.services.quantum_explainability.foundation import canonical_json


def make_dataset(tmp_path: Path, rows):
    ds = tmp_path / "quantum_research_dataset.jsonl"
    ds.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    manifest = {
        "manifest_version": "dvs-quantum-dataset-manifest-v1",
        "dataset_schema_version": "dvs-quantum-dataset-v1",
        "dataset_file": ds.name,
        "dataset_sha256": hashlib.sha256(ds.read_bytes()).hexdigest(),
        "readiness_state": "RESEARCH_CANDIDATE_ONLY",
        "integrity_findings": [{"code": "QG01", "passed": True, "detail": "ok", "count": 0}],
    }
    manifest["self_sha256"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    mf = tmp_path / "quantum_research_dataset.manifest.json"
    mf.write_text(json.dumps(manifest), encoding="utf-8")
    return ds, mf


def row(i: int, observed: bool, realized_r: float, *, month: int = 1, symbol: str = "BTCUSDT"):
    return {
        "sample_id": f"QDS-{i}", "setup_episode_id": f"episode-{i}", "candidate_id": f"candidate-{i}",
        "activation_evaluation_id": f"eval-{i}", "first_evaluation_id": f"eval-{i}",
        "first_eligible_timestamp": f"2026-{month:02d}-{(i % 27) + 1:02d}T00:00:00+00:00",
        "policy_scope_id": "QPS-1", "policy_scope_hash": "scope-hash",
        "decision_engine_checksum": "engine-hash", "trade_plan_profile_hash": "plan-hash",
        "source_row_hash": f"source-{i}", "market_event_cluster_id": f"cluster-{i}",
        "symbol": symbol, "regime": "TREND" if i % 2 else "RANGE",
        "cmf": 0.2 if observed else None, "outcome_status": "WIN" if realized_r > 0 else "LOSS",
        "realized_r": realized_r,
    }


def test_low_effective_n_is_unobservable(tmp_path):
    ds, mf = make_dataset(tmp_path, [row(i, i % 2 == 0, 1.0 if i % 2 == 0 else -1.0) for i in range(10)])
    result = UncertaintyEstimator(ds, mf, bootstrap_iterations=200).run(AblationStudy("cmf", "cmf"))
    assert result.state == UncertaintyState.UNOBSERVABLE
    assert result.diagnostics.association_class == AssociationClass.UNOBSERVABLE
    assert "EFFECTIVE_SAMPLE_SIZE_BELOW_MINIMUM" in result.diagnostics.reasons


def test_clear_noncausal_association_is_classified(tmp_path):
    rows = []
    for i in range(60):
        observed = i % 2 == 0
        rows.append(row(i, observed, 1.0 if observed else -1.0, month=(i % 3) + 1, symbol="BTCUSDT" if i % 4 else "ETHUSDT"))
    ds, mf = make_dataset(tmp_path, rows)
    result = UncertaintyEstimator(ds, mf, bootstrap_iterations=500).run(AblationStudy("cmf", "cmf"))
    assert result.state == UncertaintyState.COMPLETED
    assert result.diagnostics.association_class == AssociationClass.ASSOCIATED
    ci = result.diagnostics.confidence_interval
    assert ci.lower is not None and ci.lower > 0
    assert result.manifest["causal_claim_allowed"] is False


def test_large_stable_multisymbol_multifold_is_robust_association(tmp_path):
    rows = []
    for i in range(120):
        observed = i % 2 == 0
        rows.append(row(i, observed, 1.25 if observed else -0.75, month=(i % 4) + 1, symbol="BTCUSDT" if i % 3 else "ETHUSDT"))
    ds, mf = make_dataset(tmp_path, rows)
    result = UncertaintyEstimator(ds, mf, bootstrap_iterations=500).run(AblationStudy("cmf", "cmf"))
    assert result.diagnostics.association_class == AssociationClass.ROBUST_ASSOCIATION
    assert result.coverage.effective_n >= 100
    assert result.coverage.temporal_fold_n >= 3


def test_invalid_replay_blocks_uncertainty(tmp_path):
    bad = row(1, True, 1.0)
    bad["activation_evaluation_id"] = "later"
    ds, mf = make_dataset(tmp_path, [bad])
    result = UncertaintyEstimator(ds, mf, bootstrap_iterations=200).run(AblationStudy("cmf", "cmf"))
    assert result.state == UncertaintyState.REPLAY_BLOCKED


def test_export_is_self_sealed_and_tamper_detected(tmp_path):
    rows = [row(i, i % 2 == 0, 1.0 if i % 2 == 0 else -1.0) for i in range(40)]
    ds, mf = make_dataset(tmp_path, rows)
    result = UncertaintyEstimator(ds, mf, bootstrap_iterations=200).run(AblationStudy("cmf", "cmf"))
    result_path, manifest_path = result.export(tmp_path / "out")
    ok, detail = verify_uncertainty_bundle(result_path, manifest_path)
    assert ok, detail
    result_path.write_text(result_path.read_text() + " ", encoding="utf-8")
    ok, detail = verify_uncertainty_bundle(result_path, manifest_path)
    assert not ok and "checksum" in detail


def test_forbidden_outcome_target_is_rejected(tmp_path):
    ds, mf = make_dataset(tmp_path, [row(i, i % 2 == 0, 1.0) for i in range(40)])
    result = UncertaintyEstimator(ds, mf, bootstrap_iterations=200).run(AblationStudy("bad", "realized_r"))
    assert result.state == UncertaintyState.INVALID_STUDY
    assert "OUTCOME_OR_FUTURE_FIELD_CANNOT_BE_ABLATED_AS_EVIDENCE" in result.violations
