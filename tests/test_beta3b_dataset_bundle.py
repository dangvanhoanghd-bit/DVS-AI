from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dvs_ai.services.beta3_dataset_bundle import DatasetBuilder, DatasetBundleVerifier
from dvs_ai.services.beta3_learning_foundation import (
    FeatureStoreProjector,
    LearningCandidateBuilder,
    PolicyIdentity,
    canonical_sha256,
)
from dvs_ai.services.unified_outcome_service import UnifiedOutcomeRecord

ENGINE_SHA = "00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce"
POLICY = PolicyIdentity(ENGINE_SHA, "qg13:decision-core:v1", "scope-hash-v1")
CLOCK = lambda: datetime(2026, 7, 23, 4, 0, tzinfo=timezone.utc)


class Source:
    def __init__(self, rows): self.rows = rows
    def learning_ready(self): return list(self.rows)


def raw_record(index: int, *, policy_snapshot=None):
    evidence = policy_snapshot or {"cmf": 0.1 + index / 1000, "rsi": 50.0 + index % 20, "regime": "TREND"}
    return UnifiedOutcomeRecord(
        unified_id=f"u{index}", source_identities=(f"candidate_outcomes:c{index}",),
        candidate_id=f"c{index}", paper_trade_id=None, symbol="BTCUSDT", direction="LONG",
        outcome_status="WIN" if index % 2 == 0 else "LOSS", identity_status="EXPLICIT_SOURCE_IDENTITY",
        eligibility_status="UNIFIED_ELIGIBLE", eligibility_reason="EXPLICIT_SOURCE_IDENTITY",
        feature_snapshot_hash=canonical_sha256(evidence), realized_r=1.0 if index % 2 == 0 else -1.0,
        evidence_snapshot=evidence, resolution_source="AUTOMATIC",
    )


def governed(count: int, *, policy=POLICY):
    records = [raw_record(i) for i in range(count)]
    candidates = LearningCandidateBuilder(Source(records), policy).build().candidates
    evidence = {record.unified_id: record.evidence_snapshot for record in records}
    rows = FeatureStoreProjector("beta3a.feature.v1", "extractor-sha-v1").project(candidates, evidence).rows
    return candidates, rows


@pytest.mark.parametrize("count", [0, 1, 29])
def test_below_minimum_is_unobservable_and_emits_no_bundle(tmp_path, count):
    candidates, rows = governed(count)
    result = DatasetBuilder(tmp_path, clock=CLOCK).build(candidates, rows)
    assert result.status == "UNOBSERVABLE"
    assert result.bundle_path is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("count,state", [
    (30,"DESCRIPTIVE_ONLY"),(99,"DESCRIPTIVE_ONLY"),(100,"RESEARCH_CANDIDATE_ONLY"),
    (299,"RESEARCH_CANDIDATE_ONLY"),(300,"VALIDATION_REVIEW_ELIGIBLE"),
    (499,"VALIDATION_REVIEW_ELIGIBLE"),(500,"BURN_IN_COMPLETE"),
])
def test_burn_in_boundaries_emit_valid_bundle(tmp_path, count, state):
    candidates, rows = governed(count)
    result = DatasetBuilder(tmp_path, clock=CLOCK).build(candidates, rows)
    assert result.status == "RELEASED"
    assert result.readiness_state == state
    assert DatasetBundleVerifier().verify(result.bundle_path).valid


def test_bundle_contains_required_files_and_self_sealed_manifest(tmp_path):
    candidates, rows = governed(30)
    result = DatasetBuilder(tmp_path, clock=CLOCK).build(candidates, rows)
    bundle = Path(result.bundle_path)
    assert {p.name for p in bundle.iterdir()} == {
        "training_dataset.jsonl", "exclusions.jsonl", "quality_report.json",
        "lineage_index.jsonl", "dataset.manifest.json",
    }
    manifest = json.loads((bundle / "dataset.manifest.json").read_text())
    assert manifest["manifest_sha256"] == result.manifest_sha256
    assert manifest["bundle_sha256"] == result.bundle_sha256
    assert manifest["decision_engine_checksum"] == ENGINE_SHA


@pytest.mark.parametrize("filename", [
    "training_dataset.jsonl", "exclusions.jsonl", "quality_report.json", "lineage_index.jsonl",
])
def test_one_byte_tamper_is_detected(tmp_path, filename):
    candidates, rows = governed(30)
    result = DatasetBuilder(tmp_path, clock=CLOCK).build(candidates, rows)
    path = Path(result.bundle_path) / filename
    path.write_bytes(path.read_bytes() + b"x")
    verified = DatasetBundleVerifier().verify(result.bundle_path)
    assert not verified.valid
    assert any(filename in error for error in verified.errors)


def test_manifest_tamper_is_detected(tmp_path):
    candidates, rows = governed(30)
    result = DatasetBuilder(tmp_path, clock=CLOCK).build(candidates, rows)
    path = Path(result.bundle_path) / "dataset.manifest.json"
    manifest = json.loads(path.read_text())
    manifest["record_count"] = 999
    path.write_text(json.dumps(manifest), encoding="utf-8")
    verified = DatasetBundleVerifier().verify(result.bundle_path)
    assert "MANIFEST_SHA256_MISMATCH" in verified.errors


def test_mixed_policy_is_blocked_before_files_are_written(tmp_path):
    candidates, rows = governed(29)
    other_candidates, other_rows = governed(1, policy=PolicyIdentity(ENGINE_SHA, "other", "other-hash"))
    result = DatasetBuilder(tmp_path, clock=CLOCK).build(candidates + other_candidates, rows + other_rows)
    assert result.status == "BLOCKED"
    assert "MIXED_POLICY_IDENTITY" in result.errors
    assert not list(tmp_path.iterdir())


def test_mixed_extractor_identity_is_blocked(tmp_path):
    candidates, rows = governed(30)
    rows = list(rows)
    rows[0] = replace(rows[0], extractor_checksum="other")
    result = DatasetBuilder(tmp_path, clock=CLOCK).build(candidates, rows)
    assert result.status == "BLOCKED"
    assert result.errors == ("MIXED_EXTRACTOR_IDENTITY",)


def test_missing_feature_rows_blocks_release(tmp_path):
    candidates, rows = governed(30)
    missing_id = candidates[-1].learning_candidate_id
    filtered = [row for row in rows if row.learning_candidate_id != missing_id]
    result = DatasetBuilder(tmp_path, clock=CLOCK).build(candidates, filtered)
    assert result.status == "BLOCKED"
    assert any(error.startswith("MISSING_FEATURE_ROWS") for error in result.errors)


def test_orphan_feature_row_blocks_release(tmp_path):
    candidates, rows = governed(30)
    bad = replace(rows[0], learning_candidate_id="orphan")
    result = DatasetBuilder(tmp_path, clock=CLOCK).build(candidates, list(rows) + [bad])
    assert result.status == "BLOCKED"
    assert "ORPHAN_FEATURE_ROW" in result.errors


def test_feature_snapshot_lineage_mismatch_blocks_release(tmp_path):
    candidates, rows = governed(30)
    bad = replace(rows[0], feature_snapshot_hash="wrong")
    result = DatasetBuilder(tmp_path, clock=CLOCK).build(candidates, [bad] + list(rows[1:]))
    assert result.status == "BLOCKED"
    assert any(error.startswith("FEATURE_SNAPSHOT_HASH_MISMATCH") for error in result.errors)


def test_invalid_feature_blocks_release(tmp_path):
    candidates, rows = governed(30)
    bad = replace(rows[0], quality="INVALID")
    result = DatasetBuilder(tmp_path, clock=CLOCK).build(candidates, [bad] + list(rows[1:]))
    assert result.status == "BLOCKED"
    assert any(error.startswith("INVALID_FEATURE") for error in result.errors)


def test_lineage_is_complete_and_matches_every_dataset_row(tmp_path):
    candidates, rows = governed(30)
    result = DatasetBuilder(tmp_path, clock=CLOCK).build(candidates, rows)
    bundle = Path(result.bundle_path)
    dataset = [json.loads(line) for line in (bundle / "training_dataset.jsonl").read_text().splitlines()]
    lineage = [json.loads(line) for line in (bundle / "lineage_index.jsonl").read_text().splitlines()]
    assert {row["dataset_row_id"] for row in dataset} == {row["dataset_row_id"] for row in lineage}
    assert all(row["unified_id"] and row["feature_snapshot_hash"] and row["source_identities"] for row in lineage)
    assert all(row["feature_rows"] for row in lineage)


def test_missing_lineage_file_blocks_verification(tmp_path):
    candidates, rows = governed(30)
    result = DatasetBuilder(tmp_path, clock=CLOCK).build(candidates, rows)
    (Path(result.bundle_path) / "lineage_index.jsonl").unlink()
    verified = DatasetBundleVerifier().verify(result.bundle_path)
    assert not verified.valid
    assert "FILE_MISSING:lineage_index.jsonl" in verified.errors


def test_quality_report_accounts_for_exclusions(tmp_path):
    candidates, rows = governed(30)
    result = DatasetBuilder(tmp_path, clock=CLOCK).build(candidates, rows, exclusions=[{"unified_id":"x","reason":"NO_SNAPSHOT"}])
    quality = json.loads((Path(result.bundle_path) / "quality_report.json").read_text())
    assert quality["qualified_samples"] == 30
    assert quality["excluded_samples"] == 1
    assert quality["coverage"] == pytest.approx(30 / 31)


def test_bundle_is_deterministic_for_fixed_clock_and_inputs(tmp_path):
    candidates, rows = governed(30)
    first = DatasetBuilder(tmp_path / "a", clock=CLOCK).build(candidates, rows)
    second = DatasetBuilder(tmp_path / "b", clock=CLOCK).build(candidates, rows)
    assert first.dataset_id == second.dataset_id
    assert first.bundle_sha256 == second.bundle_sha256


def test_immutable_existing_bundle_is_not_overwritten(tmp_path):
    candidates, rows = governed(30)
    builder = DatasetBuilder(tmp_path, clock=CLOCK)
    first = builder.build(candidates, rows)
    second = builder.build(candidates, rows)
    assert first.status == "RELEASED"
    assert second.status == "BLOCKED"
    assert second.errors == ("IMMUTABLE_BUNDLE_ALREADY_EXISTS",)


def test_parent_bundle_hash_is_preserved_for_rollback_chain(tmp_path):
    candidates, rows = governed(30)
    parent = DatasetBuilder(tmp_path / "parent", clock=CLOCK).build(candidates, rows)
    later_clock = lambda: datetime(2026, 7, 24, 4, 0, tzinfo=timezone.utc)
    child = DatasetBuilder(tmp_path / "child", clock=later_clock).build(candidates, rows, parent_bundle_sha256=parent.bundle_sha256)
    manifest = json.loads((Path(child.bundle_path) / "dataset.manifest.json").read_text())
    assert manifest["parent_bundle_sha256"] == parent.bundle_sha256
    assert DatasetBundleVerifier().verify(parent.bundle_path).valid
    assert DatasetBundleVerifier().verify(child.bundle_path).valid


def test_module_has_no_database_or_training_dependency():
    import inspect
    import dvs_ai.services.beta3_dataset_bundle as module
    source = inspect.getsource(module)
    assert "sqlite3" not in source
    assert "paper_trades" not in source
    assert ".fit(" not in source
    assert "train_model" not in source


def test_r3_bundle_lineage_contains_additive_temporal_compatibility_fields(tmp_path):
    timestamp = "2026-07-23T03:45:00Z"
    records = [replace(raw_record(i), setup_time=timestamp) for i in range(30)]
    candidates = LearningCandidateBuilder(Source(records), POLICY).build().candidates
    evidence = {item.unified_id: item.evidence_snapshot for item in records}
    rows = FeatureStoreProjector("beta3a.feature.v1", "extractor-sha-v1").project(candidates, evidence).rows
    result = DatasetBuilder(tmp_path, clock=CLOCK).build(candidates, rows)
    lineage = [json.loads(line) for line in (Path(result.bundle_path) / "lineage_index.jsonl").read_text().splitlines()]
    assert result.status == "RELEASED"
    assert all(row["first_eligible_evaluation_timestamp"] == timestamp for row in lineage)
    assert all(row["snapshot_timestamp"] == timestamp for row in lineage)
    assert all(
        feature["first_eligible_evaluation_timestamp"] == timestamp
        and feature["snapshot_timestamp"] == timestamp
        for row in lineage for feature in row["feature_rows"]
    )
