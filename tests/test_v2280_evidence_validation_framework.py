import json
from pathlib import Path

from dvs_ai.services.candidate_evidence_service import CandidateComparisonEngine, CandidateEvidenceRepository
from dvs_ai.services.shadow_observation_service import ShadowObservationStore, PromotionReadinessAudit


def report(base_r=.10, cand_r=.16, base_dd=2.0, cand_dd=2.1, base_b=.20, cand_b=.19, n=40):
    return {"state":"PASS","baseline":{"n":40,"avg_r":base_r,"max_dd":base_dd,"brier":base_b},
            "candidate":{"n":n,"avg_r":cand_r,"max_dd":cand_dd,"brier":cand_b}}


def test_candidate_comparison_uses_same_holdout_metrics():
    result=CandidateComparisonEngine(min_trades=20).compare(report())
    assert result.state=='BETTER'
    assert any('expectancy_delta' in x for x in result.reasons)
    assert CandidateComparisonEngine(min_trades=20).compare(report(cand_r=-.1)).state=='WORSE'


def test_candidate_repository_reads_pending_and_promotion_timeline(tmp_path):
    data=tmp_path/'data'; promo=data/'shadow_promotions'; promo.mkdir(parents=True)
    (data/'quantum_shadow_candidate.json').write_text(json.dumps({'schema':'X','generated_at':'2026-01-01'}))
    (data/'quantum_shadow_backtest.json').write_text(json.dumps(report()))
    (promo/'promotion_1.json').write_text(json.dumps({'candidate_schema':'X','applied_at':'2026-01-02','backtest_state':'PASS'}))
    repo=CandidateEvidenceRepository(str(data),str(promo))
    rows=repo.list_candidates()
    assert {x['promotion_state'] for x in rows}=={'PENDING','APPLIED'}
    assert len(repo.timeline())==2


def test_observation_store_is_append_only_and_paired(tmp_path):
    store=ShadowObservationStore(str(tmp_path/'obs.db'))
    first=store.append(candidate_id='C1',symbol='BTCUSDT',direction='LONG',regime='BULL',
        baseline_decision='WAIT',shadow_decision='READY',baseline_score=55,shadow_score=72,truth={'drift':'STABLE'})
    second=store.append(candidate_id='C1',symbol='ETHUSDT',direction='SHORT',regime='BEAR',
        baseline_decision='READY',shadow_decision='READY',baseline_score=70,shadow_score=74)
    store.close_outcome(first,1.2); store.close_outcome(second,-1.0)
    rows=store.rows('C1')
    assert [x['id'] for x in rows]==[first,second]
    assert rows[0]['baseline_decision']=='WAIT' and rows[0]['shadow_decision']=='READY'


def test_readiness_is_observe_only_and_requires_coverage():
    audit=PromotionReadinessAudit(min_samples=6,min_regime_samples=3)
    rows=[]
    for regime in ('BULL','BEAR'):
        for i in range(3):
            rows.append({'regime':regime,'outcome_r':1.0 if i<2 else -1.0,
                         'baseline_decision':'WAIT','shadow_decision':'READY'})
    result=audit.evaluate(rows)
    assert result.state=='READY_FOR_NEXT_REVIEW'
    assert result.metrics['shadow_expectancy']>result.metrics['baseline_expectancy']
    assert not hasattr(audit,'apply') and not hasattr(audit,'promote')
