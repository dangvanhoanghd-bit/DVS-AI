from dvs_ai.services.shadow_statistical_comparison import ShadowStatisticalComparison
from dvs_ai.services.shadow_observation_service import PromotionReadinessAudit


def rows(diffs, regimes=("BULL", "BEAR")):
    out=[]
    for i, diff in enumerate(diffs):
        if diff > 0:
            base, shadow, outcome = "WAIT", "READY", diff
        elif diff < 0:
            base, shadow, outcome = "READY", "WAIT", -diff
        else:
            base, shadow, outcome = "READY", "READY", 1.0
        out.append({"id":i+1,"outcome_r":outcome,"baseline_decision":base,
                    "shadow_decision":shadow,"regime":regimes[i % len(regimes)]})
    return out


def test_clear_paired_improvement_has_positive_ci_and_is_better():
    result=ShadowStatisticalComparison(min_samples=40,bootstrap_samples=1500).compare(rows([0.2]*80))
    assert result.state == "BETTER"
    assert result.ci_low > 0 and result.probability_improvement > .99


def test_small_effect_crossing_zero_is_inconclusive():
    diffs=[0.10,-0.09]*40
    result=ShadowStatisticalComparison(min_samples=40,bootstrap_samples=1500).compare(rows(diffs))
    assert result.state == "INCONCLUSIVE"
    assert result.ci_low <= 0 <= result.ci_high


def test_time_block_instability_blocks_readiness():
    diffs=[0.30]*40+[-0.20]*40
    result=ShadowStatisticalComparison(min_samples=40,bootstrap_samples=1500,min_stable_block_ratio=.75).compare(rows(diffs))
    assert result.state in {"UNSTABLE","INCONCLUSIVE"}
    audit=PromotionReadinessAudit(min_samples=60,min_regime_samples=10,statistical_min_samples=40)
    ready=audit.evaluate(rows(diffs))
    assert ready.state != "READY_FOR_NEXT_REVIEW"


def test_bootstrap_is_deterministic_and_observe_only():
    engine=ShadowStatisticalComparison(min_samples=40,bootstrap_samples=1000,random_seed=7)
    a=engine.compare(rows([0.15]*60+[-0.05]*20))
    b=engine.compare(rows([0.15]*60+[-0.05]*20))
    assert (a.ci_low,a.ci_high,a.probability_improvement)==(b.ci_low,b.ci_high,b.probability_improvement)
    assert not hasattr(engine,'apply') and not hasattr(engine,'promote')
