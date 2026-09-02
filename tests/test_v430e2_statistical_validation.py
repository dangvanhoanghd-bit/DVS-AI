from pathlib import Path

from dvs_ai.services.quantum_validation import (
    AttemptLedger, ClusterMetric, HoldoutManager, HypothesisTest,
    StabilityObservation, ValidationOrchestrator, ValidationRequest,
    ValidationState, WalkForwardFold, cluster_bootstrap_mean,
    evaluate_stability, holm_bonferroni,
)


def fold():
    return WalkForwardFold(
        "F1", "2026-01-01T00:00:00+00:00", "2026-01-31T00:00:00+00:00",
        "2026-02-02T00:00:00+00:00", "2026-02-28T00:00:00+00:00",
        "2026-03-02T00:00:00+00:00", "2026-03-31T00:00:00+00:00", 86400, 86400,
    )


def diagnostics():
    tests = (HypothesisTest("H1", 0.001), HypothesisTest("H2", 0.02), HypothesisTest("H3", 0.40))
    observations = (
        StabilityObservation("O1", 0.30, "F1", "TREND", "BTCUSDT", 0),
        StabilityObservation("O2", 0.20, "F2", "RANGE", "ETHUSDT", -1),
        StabilityObservation("O3", 0.10, "F3", "TREND", "SOLUSDT", 1),
        StabilityObservation("O4", 0.15, "F2", "RANGE", "BTCUSDT", 1),
    )
    metrics = (ClusterMetric("C1", 0.2), ClusterMetric("C2", 0.1), ClusterMetric("C3", 0.3))
    return tests, observations, metrics


def request(**overrides):
    tests, observations, metrics = diagnostics()
    values = dict(
        study_id="STUDY-E2", policy_scope_id="QPS-1", policy_scope_hash="scope-hash",
        decision_engine_checksum="engine-hash", replay_state="VERIFIED",
        effective_n=120.0, minimum_effective_n=100.0, split_method="ANCHORED_WALK_FORWARD",
        folds=(fold(),), holdout_id="H-E2", candidate_count=3,
        hypothesis_tests=tests, stability_observations=observations,
        bootstrap_metrics=metrics, require_statistical_diagnostics=True,
    )
    values.update(overrides)
    return ValidationRequest(**values)


def service(tmp_path: Path):
    holdout = HoldoutManager(tmp_path / "holdout.jsonl")
    holdout.lock("H-E2", "2026-03-02T00:00:00+00:00", "QPS-1")
    return ValidationOrchestrator(holdout, AttemptLedger(tmp_path / "attempts.jsonl"))


def test_holm_bonferroni_controls_family_wise_error():
    result = holm_bonferroni((HypothesisTest("a", 0.01), HypothesisTest("b", 0.03), HypothesisTest("c", 0.9)))
    assert result.valid and result.rejected_count == 1
    assert result.tests[0].adjusted_p_value == 0.03


def test_invalid_p_value_fails_closed():
    result = holm_bonferroni((HypothesisTest("a", 1.5),))
    assert not result.valid and "INVALID_P_VALUE" in result.violations


def test_stability_requires_fold_regime_symbol_and_neighborhood_coverage():
    _, observations, _ = diagnostics()
    result = evaluate_stability(observations)
    assert result.valid and result.stable
    assert result.fold_count == 3 and result.regime_count == 2 and result.symbol_count == 3


def test_unstable_parameter_neighborhood_is_blocked():
    observations = (
        StabilityObservation("O1", 0.3, "F1", "TREND", "BTC", 0),
        StabilityObservation("O2", -0.2, "F2", "RANGE", "ETH", 1),
        StabilityObservation("O3", -0.1, "F3", "TREND", "SOL", -1),
    )
    result = evaluate_stability(observations)
    assert not result.stable


def test_cluster_bootstrap_is_reproducible():
    _, _, metrics = diagnostics()
    first = cluster_bootstrap_mean(metrics, resamples=500, seed=7)
    second = cluster_bootstrap_mean(metrics, resamples=500, seed=7)
    assert first == second and first.valid


def test_orchestrator_passes_complete_statistical_protocol(tmp_path):
    result = service(tmp_path).validate(request())
    assert result.state is ValidationState.PASS
    assert result.manifest["statistical_diagnostics"]["causal_claim_allowed"] is False


def test_orchestrator_blocks_missing_required_diagnostics(tmp_path):
    result = service(tmp_path).validate(request(hypothesis_tests=(), stability_observations=(), bootstrap_metrics=()))
    assert result.state is ValidationState.BLOCK
    assert "MULTIPLE_COMPARISON_INVALID" in result.violations
    assert "STABILITY_NOT_DEMONSTRATED" in result.violations
    assert "BOOTSTRAP_INVALID" in result.violations
