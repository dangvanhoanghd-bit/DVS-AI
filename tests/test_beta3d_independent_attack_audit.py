from __future__ import annotations

from dataclasses import replace

from dvs_ai.services.beta3_cross_bundle import (
    BundleComparator,
    CrossBundleDiagnosticsEngine,
    EvolutionTimeline,
    PromotionRecommender,
    RegistryEntry,
)


def e(sha: str, **kwargs) -> RegistryEntry:
    base = RegistryEntry(
        bundle_path=f"/{sha}", dataset_id=f"dataset-{sha}", bundle_sha256=sha,
        parent_bundle_sha256=None, build_timestamp="2026-07-23T00:00:00Z",
        decision_engine_checksum="de", policy_scope_id="policy", policy_scope_hash="scope",
        extractor_checksum="extractor", extractor_schema_version="v1",
        burn_in_level="RESEARCH_CANDIDATE_ONLY", record_count=100,
        coverage_ratio=.9, beta3b_quality_score=.9, hard_block=False,
    )
    return replace(base, **kwargs)


def test_attack_01_different_policy_never_competes_for_single_global_winner():
    rows = [e("a1"), e("a2"), e("b1", policy_scope_id="other"), e("b2", policy_scope_id="other")]
    result = PromotionRecommender().recommend(rows)
    assert result.recommendations["a1"] == "TRAINING_CANDIDATE"
    assert result.recommendations["b1"] == "TRAINING_CANDIDATE"


def test_attack_02_different_extractor_never_competes_across_cohorts():
    rows = [e("a1"), e("a2"), e("x1", extractor_checksum="x"), e("x2", extractor_checksum="x")]
    result = PromotionRecommender().recommend(rows)
    assert result.recommendations["a1"] == "TRAINING_CANDIDATE"
    assert result.recommendations["x1"] == "TRAINING_CANDIDATE"


def test_attack_03_singleton_confounded_bundle_is_only_eligible():
    result = PromotionRecommender().recommend([e("a1"), e("a2"), e("x", extractor_checksum="x")])
    assert result.recommendations["x"] == "ELIGIBLE_CANDIDATE"


def test_attack_04_broken_parent_does_not_poison_unrelated_parented_bundle():
    root=e("root")
    good=e("good", parent_bundle_sha256="root")
    bad=e("bad", parent_bundle_sha256="missing")
    result=PromotionRecommender().recommend([root,good,bad])
    assert result.recommendations["bad"] == "REJECTED"
    assert result.recommendations["good"] != "REJECTED"


def test_attack_05_cycle_only_rejects_cycle_members():
    a=e("a", parent_bundle_sha256="b"); b=e("b", parent_bundle_sha256="a"); c=e("c")
    result=PromotionRecommender().recommend([a,b,c])
    assert result.recommendations["a"] == result.recommendations["b"] == "REJECTED"
    assert result.recommendations["c"] == "ELIGIBLE_CANDIDATE"


def test_attack_06_cross_policy_child_rejected_but_parent_kept():
    p=e("p"); c=e("c", parent_bundle_sha256="p", policy_scope_id="other")
    result=PromotionRecommender().recommend([p,c])
    assert result.recommendations["c"] == "REJECTED"
    assert result.recommendations["p"] == "ELIGIBLE_CANDIDATE"


def test_attack_07_low_burn_in_disables_all_interpretations():
    r=BundleComparator().compare(e("a", burn_in_level="DESCRIPTIVE_ONLY"), e("b"))
    assert r.comparison_state == "COMPARISON_UNOBSERVABLE"
    assert set(r.interpretations.values()) == {None}


def test_attack_08_type_b_has_raw_metrics_but_no_labels():
    r=BundleComparator().compare(e("a"), e("b", extractor_checksum="x"))
    assert r.raw_metrics and set(r.interpretations.values()) == {None}


def test_attack_09_type_c_has_raw_metrics_but_no_labels():
    r=BundleComparator().compare(e("a"), e("b", policy_scope_id="x"))
    assert r.raw_metrics and set(r.interpretations.values()) == {None}


def test_attack_10_threshold_5_percent_is_minor():
    r=BundleComparator().compare(e("a", record_count=100), e("b", record_count=105))
    assert r.interpretations["record_count"] == "MINOR_SHIFT"


def test_attack_11_threshold_15_percent_is_moderate():
    r=BundleComparator().compare(e("a", record_count=100), e("b", record_count=115))
    assert r.interpretations["record_count"] == "MODERATE_SHIFT"


def test_attack_12_threshold_30_percent_is_major():
    r=BundleComparator().compare(e("a", record_count=100), e("b", record_count=130))
    assert r.interpretations["record_count"] == "MAJOR_SHIFT"


def test_attack_13_negative_change_uses_magnitude_only():
    r=BundleComparator().compare(e("a", record_count=100), e("b", record_count=70))
    assert r.interpretations["record_count"] == "MAJOR_SHIFT"


def test_attack_14_zero_to_nonzero_is_undefined_not_infinite():
    r=BundleComparator().compare(e("a", coverage_ratio=0), e("b", coverage_ratio=.2))
    assert r.raw_metrics["coverage_ratio"]["relative_change"] is None


def test_attack_15_timeline_uses_parent_hash_not_timestamp():
    t=EvolutionTimeline().build([e("p", build_timestamp="2026-07-30T00:00:00Z"), e("c", parent_bundle_sha256="p", build_timestamp="2026-07-01T00:00:00Z")])
    assert t.edges == ({"parent":"p","child":"c"},)


def test_attack_16_fork_is_anomaly_not_data_loss():
    t=EvolutionTimeline().build([e("p"),e("a",parent_bundle_sha256="p"),e("b",parent_bundle_sha256="p")])
    assert "FORKED_LINEAGE" in t.anomalies and len(t.edges)==2


def test_attack_17_duplicate_identity_is_explicit():
    assert "DUPLICATE_BUNDLE_IDENTITY" in EvolutionTimeline().build([e("a"),e("a")]).anomalies


def test_attack_18_pareto_tradeoff_keeps_both():
    r=PromotionRecommender().recommend([e("a",coverage_ratio=.95,beta3b_quality_score=.7),e("b",coverage_ratio=.8,beta3b_quality_score=.95)])
    assert set(r.ordered_candidates)=={"a","b"}


def test_attack_19_input_order_does_not_change_recommendations():
    rows=[e("a"),e("b"),e("x",extractor_checksum="x")]
    r=PromotionRecommender()
    assert r.recommend(rows).recommendations == r.recommend(list(reversed(rows))).recommendations


def test_attack_20_engine_orients_pair_by_verified_build_timestamp(tmp_path, monkeypatch):
    # Isolate orchestration: registry output deliberately SHA-sorted opposite to time.
    engine=CrossBundleDiagnosticsEngine()
    older=e("z",build_timestamp="2026-07-01T00:00:00Z",record_count=100)
    newer=e("a",build_timestamp="2026-07-02T00:00:00Z",record_count=120)
    from dvs_ai.services.beta3_cross_bundle import RegistryResult
    monkeypatch.setattr(engine.registry,"rebuild",lambda paths: RegistryResult("PASS",(newer,older),()))
    report=engine.run([])
    metric=report["comparisons"][0].raw_metrics["record_count"]
    assert metric["baseline_value"]==100 and metric["comparison_value"]==120


def test_attack_21_no_weighted_fitness_field_or_score():
    r=PromotionRecommender().recommend([e("a"),e("b")])
    assert not hasattr(r,"score")
    assert "score" not in repr(r).lower()
