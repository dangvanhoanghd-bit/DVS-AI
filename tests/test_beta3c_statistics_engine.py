from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dvs_ai.services.beta3_dataset_bundle import DatasetBuilder
from dvs_ai.services.beta3_learning_foundation import FeatureStoreProjector, LearningCandidateBuilder, PolicyIdentity, canonical_sha256
from dvs_ai.services.beta3_statistics_engine import DatasetBundleReader, StatisticsEngine, DIAGNOSTIC_POLICY
from dvs_ai.services.unified_outcome_service import UnifiedOutcomeRecord

ENGINE_SHA = "00c1db1a1684896b3c06fbf4cfaeea094337f1841dc2e3cb9dfdf9013252dbce"
POLICY = PolicyIdentity(ENGINE_SHA, "qg13:decision-core:v1", "scope-hash-v1")
CLOCK = lambda: datetime(2026, 7, 23, 4, 0, tzinfo=timezone.utc)

class Source:
    def __init__(self, rows): self.rows=rows
    def learning_ready(self): return list(self.rows)

def make_bundle(tmp_path, count=30, feature_fn=None, outcomes=None, exclusions=()):
    records=[]
    for i in range(count):
        ev = feature_fn(i) if feature_fn else {"x": float(i), "regime": "TREND" if i%2==0 else "RANGE"}
        outcome = outcomes[i] if outcomes else ("WIN" if i%2==0 else "LOSS")
        records.append(UnifiedOutcomeRecord(
            unified_id=f"u{i}", source_identities=(f"candidate_outcomes:c{i}",), candidate_id=f"c{i}", paper_trade_id=None,
            symbol="BTCUSDT", direction="LONG", outcome_status=outcome, identity_status="EXPLICIT_SOURCE_IDENTITY",
            eligibility_status="UNIFIED_ELIGIBLE", eligibility_reason="EXPLICIT_SOURCE_IDENTITY", feature_snapshot_hash=canonical_sha256(ev),
            realized_r=1.0 if outcome=="WIN" else -1.0, evidence_snapshot=ev, resolution_source="AUTOMATIC"))
    candidates=LearningCandidateBuilder(Source(records), POLICY).build().candidates
    rows=FeatureStoreProjector("beta3a.feature.v1", "extractor-v1").project(candidates,{r.unified_id:r.evidence_snapshot for r in records}).rows
    result=DatasetBuilder(tmp_path, clock=CLOCK).build(candidates, rows, exclusions=exclusions)
    assert result.status=="RELEASED"
    return Path(result.bundle_path)

def reseal(bundle: Path):
    import hashlib
    from dvs_ai.services import beta3_dataset_bundle as b
    manifest=json.loads((bundle/"dataset.manifest.json").read_text())
    file_hashes={name:b._file_sha256(bundle/name) for name in b.BUNDLE_FILES}
    manifest["files"]={name:{"sha256":h} for name,h in file_hashes.items()}
    material={k:v for k,v in manifest.items() if k not in {"manifest_sha256","bundle_sha256"}}
    manifest["manifest_sha256"]=hashlib.sha256(b._canonical_bytes(material)).hexdigest()
    manifest["bundle_sha256"]=hashlib.sha256(b._canonical_bytes({"manifest_sha256":manifest["manifest_sha256"],"files":file_hashes})).hexdigest()
    (bundle/"dataset.manifest.json").write_bytes(b._canonical_bytes(manifest)+b"\n")

@pytest.mark.parametrize("filename", ["training_dataset.jsonl","exclusions.jsonl","quality_report.json","lineage_index.jsonl","dataset.manifest.json"])
def test_reader_hard_blocks_tamper(tmp_path, filename):
    bundle=make_bundle(tmp_path)
    (bundle/filename).write_bytes((bundle/filename).read_bytes()+b"x")
    result=StatisticsEngine().run(bundle, verify_current_engine=False)
    assert result.status=="HARD_BLOCK" and result.report is None

def test_reader_rejects_multiple_bundles(tmp_path):
    data, errors=DatasetBundleReader().read([str(tmp_path/'a'),str(tmp_path/'b')])
    assert data is None and errors==("MULTI_BUNDLE_INPUT_NOT_ALLOWED",)

def test_descriptive_statistics_exact(tmp_path):
    bundle=make_bundle(tmp_path, feature_fn=lambda i:{"x":float(i+1)})
    r=StatisticsEngine().run(bundle, verify_current_engine=False).report["descriptive_statistics"]["x"]
    assert r["count"]==30 and r["mean"]==pytest.approx(15.5) and r["median"]==pytest.approx(15.5)
    assert r["min"]==1 and r["max"]==30 and r["p25"]==pytest.approx(8.25) and r["p75"]==pytest.approx(22.75)

def test_numeric_missing_is_counted(tmp_path):
    bundle=make_bundle(tmp_path, feature_fn=lambda i:{"x":float(i)})
    # Beta3B blocks INVALID, so patch a released bundle and align quality truth.
    rows=[json.loads(x) for x in (bundle/"training_dataset.jsonl").read_text().splitlines()]
    rows[0]["features"]["x"]=None; rows[0]["feature_quality"]["x"]="WARNING"
    (bundle/"training_dataset.jsonl").write_text("".join(json.dumps(x,sort_keys=True,separators=(",",":"))+"\n" for x in rows))
    q=json.loads((bundle/"quality_report.json").read_text()); q["valid_feature_count"]-=1; q["feature_completeness"]=q["valid_feature_count"]/q["feature_count"]
    (bundle/"quality_report.json").write_text(json.dumps(q,sort_keys=True,separators=(",",":"))+"\n"); reseal(bundle)
    report=StatisticsEngine().run(bundle, verify_current_engine=False).report
    assert report["descriptive_statistics"]["x"]["missing_count"]==1
    assert report["missingness"]["features"]["x"]["classification"]=="MISSING_WITHOUT_DECLARED_REASON"

def test_zero_iqr_is_explicit(tmp_path):
    bundle=make_bundle(tmp_path, feature_fn=lambda i:{"x":5.0})
    out=StatisticsEngine().run(bundle, verify_current_engine=False).report["descriptive_statistics"]["x"]["outlier"]
    assert out["state"]=="ZERO_IQR" and out["outlier_count"]==0

def test_iqr_outlier_detection(tmp_path):
    bundle=make_bundle(tmp_path, feature_fn=lambda i:{"x":1000.0 if i==29 else float(i%5)})
    out=StatisticsEngine().run(bundle, verify_current_engine=False).report["descriptive_statistics"]["x"]["outlier"]
    assert out["outlier_count"]==1 and out["state"]=="ELEVATED_OUTLIER_RATE"

def test_no_zscore_or_inference_terms():
    import dvs_ai.services.beta3_statistics_engine as m
    source=inspect.getsource(m)
    assert "zscore" not in source.lower() and "little" not in source.lower()
    for label in ("MCAR","MAR","MNAR"):
        assert label not in json.dumps(DIAGNOSTIC_POLICY)

def test_categorical_distribution_has_no_imbalance_label(tmp_path):
    bundle=make_bundle(tmp_path)
    cat=StatisticsEngine().run(bundle, verify_current_engine=False).report["categorical_feature_distribution"]["regime"]
    assert cat["frequencies"]=={"RANGE":15,"TREND":15}
    assert "state" not in cat and "imbalance" not in json.dumps(cat).lower()

@pytest.mark.parametrize("wins,expected", [(15,"BALANCED"),(18,"MILD_IMBALANCE"),(21,"MODERATE_IMBALANCE"),(24,"SEVERE_IMBALANCE")])
def test_outcome_balance_thresholds(tmp_path,wins,expected):
    outcomes=["WIN"]*wins+["LOSS"]*(30-wins)
    bundle=make_bundle(tmp_path,outcomes=outcomes)
    assert StatisticsEngine().run(bundle,verify_current_engine=False).report["outcome_balance"]["state"]==expected

def test_non_binary_outcome_hard_block(tmp_path):
    bundle=make_bundle(tmp_path)
    rows=[json.loads(x) for x in (bundle/"training_dataset.jsonl").read_text().splitlines()]
    rows[0]["outcome_status"]="OPEN"
    (bundle/"training_dataset.jsonl").write_text("".join(json.dumps(x,sort_keys=True,separators=(",",":"))+"\n" for x in rows)); reseal(bundle)
    result=StatisticsEngine().run(bundle,verify_current_engine=False)
    assert result.status=="HARD_BLOCK" and "NON_BINARY_OUTCOME_IN_DATASET" in result.hard_block_errors

def test_quality_mismatch_hard_blocks_without_report(tmp_path):
    bundle=make_bundle(tmp_path)
    q=json.loads((bundle/"quality_report.json").read_text()); q["valid_feature_count"]-=1
    (bundle/"quality_report.json").write_text(json.dumps(q,sort_keys=True,separators=(",",":"))+"\n"); reseal(bundle)
    result=StatisticsEngine().run(bundle,verify_current_engine=False)
    assert result.status=="HARD_BLOCK" and result.report is None and "QUALITY_AGGREGATION_MISMATCH" in result.hard_block_errors

def test_quality_is_aggregation_only(tmp_path):
    bundle=make_bundle(tmp_path)
    report=StatisticsEngine().run(bundle,verify_current_engine=False).report
    assert report["feature_quality_aggregation"]["x"]=={"VALID":30}
    assert "quality_score" not in report["feature_quality_aggregation"]

def test_coverage_is_within_single_bundle(tmp_path):
    bundle=make_bundle(tmp_path)
    report=StatisticsEngine().run(bundle,verify_current_engine=False).report
    assert report["coverage"]["x"]["coverage_rate"]==1.0
    assert report["dataset_identity"]["policy_scope_id"]==POLICY.policy_scope_id

def test_exclusions_report_known_reason(tmp_path):
    bundle=make_bundle(tmp_path,exclusions=[{"unified_id":"z","reason":"NO_SNAPSHOT"}])
    m=StatisticsEngine().run(bundle,verify_current_engine=False).report["missingness"]["eligibility_exclusions"]
    assert m["classification"]=="MISSING_BY_ELIGIBILITY_EXCLUSION" and m["counts_by_reason"]=={"NO_SNAPSHOT":1}

def test_runtime_not_requested_soft_blocks_and_emits_report(tmp_path):
    result=StatisticsEngine().run(make_bundle(tmp_path),verify_current_engine=False)
    assert result.status=="SOFT_BLOCK" and result.report is not None and not result.release_eligible
    assert result.report["runtime_environment_attestation"]["state"]=="NOT_REQUESTED"

def test_runtime_missing_file_soft_blocks(tmp_path):
    result=StatisticsEngine().run(make_bundle(tmp_path),current_engine_path=tmp_path/"missing.py")
    assert result.status=="SOFT_BLOCK" and "CURRENT_ENGINE_FILE_UNAVAILABLE" in result.soft_block_reasons

def test_runtime_mismatch_soft_blocks(tmp_path):
    engine=tmp_path/"engine.py"; engine.write_text("changed")
    result=StatisticsEngine().run(make_bundle(tmp_path/"b"),current_engine_path=engine)
    assert result.status=="SOFT_BLOCK" and "CURRENT_DECISION_ENGINE_MISMATCH" in result.soft_block_reasons

def test_runtime_match_passes(tmp_path):
    engine=tmp_path/"engine.py"; engine.write_bytes(b"frozen")
    import hashlib
    checksum=hashlib.sha256(b"frozen").hexdigest()
    global POLICY
    old=POLICY; POLICY=PolicyIdentity(checksum,"qg13:decision-core:v1","scope-hash-v1")
    try:
        result=StatisticsEngine().run(make_bundle(tmp_path/"b"),current_engine_path=engine)
        assert result.status=="PASS" and result.release_eligible
    finally: POLICY=old

def test_only_three_gate_states(tmp_path):
    pass_result=StatisticsEngine().run(make_bundle(tmp_path/"p"),verify_current_engine=False)
    hard_bundle=make_bundle(tmp_path/"h"); (hard_bundle/"training_dataset.jsonl").write_bytes(b"x")
    hard_result=StatisticsEngine().run(hard_bundle,verify_current_engine=False)
    assert {pass_result.status,hard_result.status} <= {"PASS","SOFT_BLOCK","HARD_BLOCK"}

def test_report_discloses_frozen_thresholds(tmp_path):
    report=StatisticsEngine().run(make_bundle(tmp_path),verify_current_engine=False).report
    assert report["diagnostic_policy"]["policy_id"]=="beta3c.diagnostics.v1"
    assert report["diagnostic_policy"]["outlier_multiplier"]==1.5

def test_engine_does_not_modify_bundle(tmp_path):
    bundle=make_bundle(tmp_path)
    before={p.name:p.read_bytes() for p in bundle.iterdir()}
    StatisticsEngine().run(bundle,verify_current_engine=False)
    after={p.name:p.read_bytes() for p in bundle.iterdir()}
    assert before==after

def test_module_isolation():
    import dvs_ai.services.beta3_statistics_engine as m
    source=inspect.getsource(m)
    for forbidden in ("sqlite3","paper_trades","candidate_outcomes","train_model",".fit(","trade_signal"):
        assert forbidden not in source

def test_missing_by_design_requires_declared_metadata(tmp_path):
    bundle=make_bundle(tmp_path, feature_fn=lambda i:{"x":float(i)})
    rows=[json.loads(x) for x in (bundle/"training_dataset.jsonl").read_text().splitlines()]
    rows[0]["features"]["x"]=None; rows[0]["feature_quality"]["x"]="WARNING"
    (bundle/"training_dataset.jsonl").write_text("".join(json.dumps(x,sort_keys=True,separators=(",",":"))+"\n" for x in rows))
    q=json.loads((bundle/"quality_report.json").read_text()); q["valid_feature_count"]-=1; q["feature_completeness"]=q["valid_feature_count"]/q["feature_count"]
    (bundle/"quality_report.json").write_text(json.dumps(q,sort_keys=True,separators=(",",":"))+"\n")
    m=json.loads((bundle/"dataset.manifest.json").read_text()); m["features_missing_by_design"]=["x"]
    (bundle/"dataset.manifest.json").write_text(json.dumps(m,sort_keys=True,separators=(",",":"))+"\n"); reseal(bundle)
    report=StatisticsEngine().run(bundle,verify_current_engine=False).report
    assert report["missingness"]["features"]["x"]["classification"]=="MISSING_BY_DESIGN"

def test_dataset_engine_self_consistency_mismatch_hard_blocks(tmp_path):
    bundle=make_bundle(tmp_path)
    rows=[json.loads(x) for x in (bundle/"training_dataset.jsonl").read_text().splitlines()]
    rows[0]["decision_engine_checksum"]="0"*64
    (bundle/"training_dataset.jsonl").write_text("".join(json.dumps(x,sort_keys=True,separators=(",",":"))+"\n" for x in rows)); reseal(bundle)
    result=StatisticsEngine().run(bundle,verify_current_engine=False)
    assert result.status=="HARD_BLOCK" and "BUNDLE_VERIFY:DATASET_POLICY_MISMATCH" in result.hard_block_errors

def test_lineage_engine_self_consistency_mismatch_hard_blocks(tmp_path):
    bundle=make_bundle(tmp_path)
    rows=[json.loads(x) for x in (bundle/"lineage_index.jsonl").read_text().splitlines()]
    rows[0]["decision_engine_checksum"]="0"*64
    (bundle/"lineage_index.jsonl").write_text("".join(json.dumps(x,sort_keys=True,separators=(",",":"))+"\n" for x in rows)); reseal(bundle)
    result=StatisticsEngine().run(bundle,verify_current_engine=False)
    assert result.status=="HARD_BLOCK" and "BUNDLE_VERIFY:LINEAGE_POLICY_MISMATCH" in result.hard_block_errors

def test_dataset_policy_scope_mismatch_hard_blocks(tmp_path):
    bundle=make_bundle(tmp_path)
    rows=[json.loads(x) for x in (bundle/"training_dataset.jsonl").read_text().splitlines()]
    rows[0]["policy_scope_hash"]="other"
    (bundle/"training_dataset.jsonl").write_text("".join(json.dumps(x,sort_keys=True,separators=(",",":"))+"\n" for x in rows)); reseal(bundle)
    result=StatisticsEngine().run(bundle,verify_current_engine=False)
    assert result.status=="HARD_BLOCK" and "BUNDLE_VERIFY:DATASET_POLICY_MISMATCH" in result.hard_block_errors

def test_categorical_proportions_sum_to_one(tmp_path):
    bundle=make_bundle(tmp_path)
    p=StatisticsEngine().run(bundle,verify_current_engine=False).report["categorical_feature_distribution"]["regime"]["proportions"]
    assert sum(p.values())==pytest.approx(1.0)

def test_outcome_raw_metrics_are_always_present(tmp_path):
    bundle=make_bundle(tmp_path,outcomes=["WIN"]*20+["LOSS"]*10)
    outcome=StatisticsEngine().run(bundle,verify_current_engine=False).report["outcome_balance"]
    assert outcome["counts"]=={"WIN":20,"LOSS":10}
    assert outcome["majority_rate"]==pytest.approx(2/3)
    assert outcome["absolute_rate_gap"]==pytest.approx(1/3)

def test_custom_threshold_policy_is_disclosed_and_used(tmp_path):
    policy=dict(DIAGNOSTIC_POLICY)
    policy["policy_id"]="beta3c.diagnostics.custom-test"
    policy["outcome_majority_rate_thresholds"]={"mild_gte":0.51,"moderate_gte":0.90,"severe_gte":0.95}
    bundle=make_bundle(tmp_path,outcomes=["WIN"]*16+["LOSS"]*14)
    report=StatisticsEngine(diagnostic_policy=policy).run(bundle,verify_current_engine=False).report
    assert report["diagnostic_policy"]["policy_id"]=="beta3c.diagnostics.custom-test"
    assert report["outcome_balance"]["state"]=="MILD_IMBALANCE"

def test_hard_block_never_contains_partial_report(tmp_path):
    bundle=make_bundle(tmp_path)
    (bundle/"quality_report.json").write_bytes(b"{}")
    result=StatisticsEngine().run(bundle,verify_current_engine=False)
    assert result.status=="HARD_BLOCK" and result.report is None and not result.release_eligible
