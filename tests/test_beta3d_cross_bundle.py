from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from dvs_ai.services.beta3_cross_bundle import (
    BURN_IN_RANK,
    COMPARISON_TYPE_A,
    COMPARISON_TYPE_B,
    COMPARISON_TYPE_C,
    BundleComparator,
    BundleRegistry,
    CrossBundleDiagnosticsEngine,
    EvolutionTimeline,
    PromotionRecommender,
    RegistryEntry,
)


def entry(sha: str, **overrides) -> RegistryEntry:
    base = dict(
        bundle_path=f"/{sha}", dataset_id=f"d-{sha}", bundle_sha256=sha,
        parent_bundle_sha256=None, build_timestamp="2026-07-23T00:00:00Z",
        decision_engine_checksum="engine-a", policy_scope_id="policy-a",
        policy_scope_hash="scope-a", extractor_checksum="extractor-a",
        extractor_schema_version="v1", burn_in_level="RESEARCH_CANDIDATE_ONLY",
        record_count=100, coverage_ratio=0.9, beta3b_quality_score=0.8,
    )
    base.update(overrides)
    return RegistryEntry(**base)


def test_policy_and_extraction_identity_are_separate():
    e = entry("a")
    assert e.policy_identity == ("policy-a", "scope-a", "engine-a")
    assert e.extraction_identity == ("v1", "extractor-a")


def test_type_a_same_policy_same_extractor():
    assert BundleComparator.classify(entry("a"), entry("b")) == COMPARISON_TYPE_A


@pytest.mark.parametrize("field,value", [
    ("extractor_checksum", "x"), ("extractor_schema_version", "v2")
])
def test_type_b_same_policy_different_extractor(field, value):
    assert BundleComparator.classify(entry("a"), replace(entry("b"), **{field:value})) == COMPARISON_TYPE_B


@pytest.mark.parametrize("field,value", [
    ("decision_engine_checksum", "x"), ("policy_scope_id", "x"), ("policy_scope_hash", "x")
])
def test_type_c_different_policy(field, value):
    assert BundleComparator.classify(entry("a"), replace(entry("b"), **{field:value})) == COMPARISON_TYPE_C


def test_raw_metrics_are_separate_from_interpretation():
    result = BundleComparator().compare(entry("a"), entry("b", record_count=120))
    assert result.raw_metrics["record_count"]["delta"] == 20
    assert result.raw_metrics["record_count"]["absolute_change"] == 20
    assert result.interpretations["record_count"] == "MODERATE_SHIFT"


@pytest.mark.parametrize("count,label", [(104,"STABLE"),(105,"MINOR_SHIFT"),(115,"MODERATE_SHIFT"),(130,"MAJOR_SHIFT")])
def test_frozen_shift_boundaries(count, label):
    result = BundleComparator().compare(entry("a"), entry("b", record_count=count))
    assert result.interpretations["record_count"] == label


def test_no_significance_language_in_labels():
    labels = BundleComparator().compare(entry("a"), entry("b", record_count=150)).interpretations.values()
    assert all("SIGNIFICANT" not in str(label) for label in labels)


def test_type_b_preserves_raw_metrics_but_disables_interpretation():
    result = BundleComparator().compare(entry("a"), entry("b", extractor_checksum="other", record_count=140))
    assert result.comparison_state == "EXTRACTOR_CONFOUNDED_CHANGE"
    assert "EXTRACTOR_CONFOUNDING_PRESENT" in result.warnings
    assert result.raw_metrics["record_count"]["delta"] == 40
    assert all(value is None for value in result.interpretations.values())


def test_type_c_is_contrast_not_evolution():
    result = BundleComparator().compare(entry("a"), entry("b", policy_scope_id="other"))
    assert result.comparison_state == "CROSS_POLICY_CONTRAST"
    assert all(value is None for value in result.interpretations.values())


def test_low_burn_in_is_unobservable_and_has_no_labels():
    result = BundleComparator().compare(entry("a", burn_in_level="DESCRIPTIVE_ONLY", record_count=30), entry("b"))
    assert result.comparison_state == "COMPARISON_UNOBSERVABLE"
    assert "LOW_CONFIDENCE_COMPARISON" in result.warnings
    assert all(value is None for value in result.interpretations.values())


def test_zero_baseline_relative_change_is_explicitly_undefined():
    result = BundleComparator().compare(entry("a", coverage_ratio=0), entry("b", coverage_ratio=.5))
    assert result.raw_metrics["coverage_ratio"]["relative_change"] is None
    assert result.interpretations["coverage_ratio"] == "UNDEFINED_BASELINE"


def test_timeline_follows_parent_sha_not_timestamp():
    a = entry("a", build_timestamp="2026-07-24T00:00:00Z")
    b = entry("b", parent_bundle_sha256="a", build_timestamp="2026-07-23T00:00:00Z")
    timeline = EvolutionTimeline().build([a,b])
    assert timeline.edges == ({"parent":"a","child":"b"},)


def test_missing_parent_detected():
    timeline = EvolutionTimeline().build([entry("b", parent_bundle_sha256="missing")])
    assert "BROKEN_PARENT_REFERENCE" in timeline.anomalies


def test_self_cycle_detected():
    assert "LINEAGE_CYCLE" in EvolutionTimeline().build([entry("a", parent_bundle_sha256="a")]).anomalies


def test_multi_node_cycle_detected():
    a = entry("a", parent_bundle_sha256="b")
    b = entry("b", parent_bundle_sha256="a")
    assert "LINEAGE_CYCLE" in EvolutionTimeline().build([a,b]).anomalies


def test_fork_detected_but_kept_as_graph():
    a = entry("a"); b = entry("b", parent_bundle_sha256="a"); c = entry("c", parent_bundle_sha256="a")
    t = EvolutionTimeline().build([a,b,c])
    assert "FORKED_LINEAGE" in t.anomalies
    assert len(t.edges) == 2


def test_extractor_change_point_detected():
    a = entry("a"); b = entry("b", parent_bundle_sha256="a", extractor_checksum="x")
    assert "EXTRACTOR_CHANGE_POINT" in EvolutionTimeline().build([a,b]).anomalies


def test_cross_policy_lineage_detected():
    a = entry("a"); b = entry("b", parent_bundle_sha256="a", policy_scope_id="x")
    assert "CROSS_POLICY_LINEAGE" in EvolutionTimeline().build([a,b]).anomalies


def test_duplicate_bundle_identity_detected():
    assert "DUPLICATE_BUNDLE_IDENTITY" in EvolutionTimeline().build([entry("a"), entry("a")]).anomalies


def test_absolute_fallback_does_not_deadlock_and_caps_label():
    result = PromotionRecommender().recommend([entry("a"), entry("b", extractor_checksum="x")])
    assert result.promotion_mode == "ABSOLUTE_ELIGIBILITY_FALLBACK"
    assert not result.comparative_evidence_available
    assert result.promotion_cap == "ELIGIBLE_CANDIDATE"
    assert set(result.recommendations.values()) == {"ELIGIBLE_CANDIDATE"}


def test_comparative_mode_requires_two_type_a_candidates():
    result = PromotionRecommender().recommend([entry("a"), entry("b")])
    assert result.promotion_mode == "COMPARATIVE_PROMOTION"
    assert result.comparative_evidence_available
    assert "TRAINING_CANDIDATE" in result.recommendations.values()


def test_hard_constraints_run_before_ranking():
    bad = entry("bad", hard_block=True, record_count=9999)
    good = entry("good")
    result = PromotionRecommender().recommend([bad,good])
    assert result.recommendations["bad"] == "REJECTED"
    assert "HARD_BLOCK_PRESENT" in result.excluded["bad"]


@pytest.mark.parametrize("kwargs,reason", [
    ({"burn_in_level":"DESCRIPTIVE_ONLY"}, "BURN_IN_BELOW_MINIMUM"),
    ({"coverage_ratio":0}, "COVERAGE_FLOOR_NOT_MET"),
    ({"beta3b_quality_score":0}, "QUALITY_FLOOR_NOT_MET"),
])
def test_individual_hard_constraints(kwargs, reason):
    result = PromotionRecommender().recommend([entry("bad", **kwargs)])
    assert reason in result.excluded["bad"]


def test_pareto_dominance_has_no_weighted_score():
    strong = entry("strong", coverage_ratio=.9, beta3b_quality_score=.9, record_count=200)
    weak = entry("weak", coverage_ratio=.8, beta3b_quality_score=.8, record_count=100)
    result = PromotionRecommender().recommend([strong,weak])
    assert result.ordered_candidates == ("strong",)


def test_tradeoff_keeps_both_on_pareto_frontier():
    a = entry("a", coverage_ratio=.95, beta3b_quality_score=.7)
    b = entry("b", coverage_ratio=.85, beta3b_quality_score=.9)
    result = PromotionRecommender().recommend([a,b])
    assert set(result.ordered_candidates) == {"a","b"}


def test_lexicographic_order_is_frozen_burn_in_first():
    a = entry("a", burn_in_level="BURN_IN_COMPLETE", coverage_ratio=.5)
    b = entry("b", burn_in_level="RESEARCH_CANDIDATE_ONLY", coverage_ratio=1.0)
    result = PromotionRecommender().recommend([a,b])
    assert result.ordered_candidates[0] == "a"


def test_lexicographic_coverage_then_quality_then_count():
    a = entry("a", coverage_ratio=.95, beta3b_quality_score=.6, record_count=100)
    b = entry("b", coverage_ratio=.90, beta3b_quality_score=1.0, record_count=1000)
    result = PromotionRecommender().recommend([a,b])
    assert result.ordered_candidates[0] == "a"


def test_build_timestamp_desc_before_sha():
    a = entry("a", build_timestamp="2026-07-23T00:00:00Z")
    b = entry("b", build_timestamp="2026-07-24T00:00:00Z")
    result = PromotionRecommender().recommend([a,b])
    assert result.ordered_candidates[0] == "b"


def test_sha_ascending_is_final_tie_break():
    result = PromotionRecommender().recommend([entry("b"),entry("a")])
    assert result.ordered_candidates[:2] == ("a","b")


def test_order_is_input_order_independent():
    r = PromotionRecommender()
    a,b = entry("a"),entry("b")
    assert r.recommend([a,b]).ordered_candidates == r.recommend([b,a]).ordered_candidates


def test_registry_stale_detection_distinguishes_path_set_change():
    from dvs_ai.services.beta3_cross_bundle import RegistryResult
    reg = RegistryResult("PASS", (entry("a", bundle_path="/a"),), ())
    assert not BundleRegistry.stale_against(reg,["/a"])
    assert BundleRegistry.stale_against(reg,["/a","/b"])


def test_module_has_no_training_database_or_prediction_dependency():
    import inspect, dvs_ai.services.beta3_cross_bundle as module
    source = inspect.getsource(module).lower()
    assert "sqlite" not in source
    assert "sklearn" not in source
    assert "fit(" not in source
    assert "predict(" not in source


def test_burn_in_scale_reuses_existing_beta3_scale():
    assert BURN_IN_RANK["DESCRIPTIVE_ONLY"] < BURN_IN_RANK["RESEARCH_CANDIDATE_ONLY"]
    assert BURN_IN_RANK["RESEARCH_CANDIDATE_ONLY"] < BURN_IN_RANK["VALIDATION_REVIEW_ELIGIBLE"]
    assert BURN_IN_RANK["VALIDATION_REVIEW_ELIGIBLE"] < BURN_IN_RANK["BURN_IN_COMPLETE"]

# Real Beta 3B bundle integration/attack tests.
def _real_bundle(tmp_path, name: str, day: int, parent=None):
    from datetime import datetime, timezone
    from dvs_ai.services.beta3_dataset_bundle import DatasetBuilder
    from dvs_ai.services.beta3_learning_foundation import FeatureStoreProjector, LearningCandidateBuilder, PolicyIdentity, canonical_sha256
    from dvs_ai.services.unified_outcome_service import UnifiedOutcomeRecord
    class Source:
        def __init__(self, rows): self.rows = rows
        def learning_ready(self): return list(self.rows)
    policy = PolicyIdentity("0"*64, "policy-real", "scope-real")
    records=[]
    for i in range(100):
        evidence={"cmf": i/100.0, "rsi": 40+i%20, "regime":"TREND"}
        records.append(UnifiedOutcomeRecord(
            unified_id=f"{name}-u{i}", source_identities=(f"source:{name}:{i}",), candidate_id=f"{name}-c{i}",
            paper_trade_id=None, symbol="BTCUSDT", direction="LONG", outcome_status="WIN" if i%2==0 else "LOSS",
            identity_status="EXPLICIT_SOURCE_IDENTITY", eligibility_status="UNIFIED_ELIGIBLE",
            eligibility_reason="EXPLICIT_SOURCE_IDENTITY", feature_snapshot_hash=canonical_sha256(evidence),
            realized_r=1.0 if i%2==0 else -1.0, evidence_snapshot=evidence, resolution_source="AUTOMATIC"))
    candidates=LearningCandidateBuilder(Source(records), policy).build().candidates
    rows=FeatureStoreProjector("beta3a.feature.v1", "extractor-real").project(candidates, {r.unified_id:r.evidence_snapshot for r in records}).rows
    clock=lambda: datetime(2026,7,day,tzinfo=timezone.utc)
    result=DatasetBuilder(tmp_path/name, clock=clock).build(candidates, rows, parent_bundle_sha256=parent)
    assert result.status == "RELEASED"
    return result


def test_real_beta3b_bundles_build_registry_compare_and_promote(tmp_path):
    first=_real_bundle(tmp_path,"first",23)
    second=_real_bundle(tmp_path,"second",24,parent=first.bundle_sha256)
    report=CrossBundleDiagnosticsEngine().run([first.bundle_path,second.bundle_path])
    assert report["registry"].status == "PASS"
    assert len(report["comparisons"]) == 1
    assert report["comparisons"][0].comparison_type == COMPARISON_TYPE_A
    assert report["promotion"].promotion_mode == "COMPARATIVE_PROMOTION"
    assert report["timeline"].edges == ({"parent":first.bundle_sha256,"child":second.bundle_sha256},)


def test_real_tampered_bundle_is_excluded_without_poisoning_good_bundle(tmp_path):
    good=_real_bundle(tmp_path,"good",23)
    bad=_real_bundle(tmp_path,"bad",24)
    path=Path(bad.bundle_path)/"training_dataset.jsonl"
    path.write_bytes(path.read_bytes()+b"tamper")
    registry=BundleRegistry().rebuild([good.bundle_path,bad.bundle_path])
    assert registry.status == "PARTIAL"
    assert len(registry.verified_entries) == 1
    assert registry.excluded_entries[0].status == "BUNDLE_VERIFICATION_FAILED_EXCLUDED"
    assert "FILE_HASH_MISMATCH:training_dataset.jsonl" in registry.excluded_entries[0].verification_error_detail


def test_real_all_corrupt_registry_is_hard_block(tmp_path):
    bad=_real_bundle(tmp_path,"bad",23)
    (Path(bad.bundle_path)/"dataset.manifest.json").write_text("{}")
    registry=BundleRegistry().rebuild([bad.bundle_path])
    assert registry.status == "HARD_BLOCK"
    assert not registry.verified_entries


def test_real_registry_is_rebuilt_from_bundle_truth_not_mutable_cache(tmp_path):
    real=_real_bundle(tmp_path,"real",23)
    one=BundleRegistry().rebuild([real.bundle_path])
    two=BundleRegistry().rebuild([real.bundle_path])
    assert one.verified_entries == two.verified_entries
    assert one.verified_entries[0].record_count == 100
