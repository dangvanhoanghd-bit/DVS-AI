import json
from datetime import datetime, timezone, timedelta
from dvs_ai.services.shadow_observation_service import ObservationQualityAudit, PromotionReadinessAudit

def row(i, *, bound=True, outcome=1.0, age=1, regime='BULL', schema='DVS_SHADOW_OBSERVATION_V1'):
    stamp=(datetime.now(timezone.utc)-timedelta(days=age)).isoformat()
    return {'id':i,'created_at':stamp,'closed_at':stamp,'paper_trade_id':i if bound else None,
            'outcome_r':outcome,'regime':regime,'baseline_decision':'WAIT','shadow_decision':'READY',
            'truth_json':json.dumps({'schema':schema})}

def test_quality_blocks_unbound_or_empty_data():
    result=ObservationQualityAudit(min_eligible=2).evaluate([row(1,bound=False),row(2,bound=False)])
    assert result.state=='BLOCKED' and result.eligible==0

def test_quality_excludes_stale_invalid_and_missing_outcomes():
    rows=[row(1),row(2,age=90),row(3,outcome=None),row(4,schema='LEGACY')]
    result=ObservationQualityAudit(min_eligible=1,max_age_days=45,min_close_rate=.2).evaluate(rows)
    assert result.eligible==1
    assert result.excluded['stale']==1 and result.excluded['missing_outcome']==1 and result.excluded['invalid_truth']==1

def test_quality_full_and_regime_coverage():
    rows=[row(i,regime='BULL' if i%2 else 'BEAR') for i in range(1,7)]
    result=ObservationQualityAudit(min_eligible=4,min_bind_rate=.5,min_close_rate=.8).evaluate(rows)
    assert result.state=='FULL' and result.regime_coverage=={'BULL':3,'BEAR':3}

def test_readiness_uses_only_quality_eligible_rows():
    good=[row(i,regime='BULL' if i%2 else 'BEAR') for i in range(1,7)]
    bad=[row(100,age=100,outcome=-10)]
    quality=ObservationQualityAudit(min_eligible=4).evaluate(good+bad)
    result=PromotionReadinessAudit(min_samples=6,min_regime_samples=3).evaluate(good+bad,quality_result=quality)
    assert result.state=='READY_FOR_NEXT_REVIEW'
    assert result.samples==6
