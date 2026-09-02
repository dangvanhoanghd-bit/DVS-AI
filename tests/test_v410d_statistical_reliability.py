from __future__ import annotations
from dvs_ai.services.outcome_analytics import OutcomeAnalyticsService
from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore
from dvs_ai.services.setup_episode_service import EvaluationCapture, SetupEpisodeService


def add_case(store, *, suffix, confidence, gates, outcome, realized_r, direction='LONG', symbol='BTCUSDT'):
    svc=SetupEpisodeService(store)
    ts=f'2026-07-20 10:{int(suffix):02d}:00'
    _,cid=svc.capture(EvaluationCapture(symbol=symbol,direction=direction,evaluated_at=ts,entry_score=60,confidence=confidence,opportunity_score=55,gate_set=tuple(gates),decision_engine_profile_hash=('d'*63)+str(int(suffix)%10),level=100+int(suffix),atr_15m=2,lifecycle='EARLY_FORMATION',entry_low=99,entry_high=100,invalidation=98,tp1=102,tp2=104,evaluation_id=f'e{suffix}'))
    with store.connect() as con:
        con.execute('update candidate_outcomes set status=?,realized_r=? where candidate_id=?',(outcome,realized_r,cid))
        con.execute('update decision_candidates set status=? where candidate_id=?',(outcome,cid))
    return cid


def test_empty_reliability_is_unobservable(tmp_path):
    r=OutcomeAnalyticsService(OutcomeInfrastructureStore(tmp_path/'x.db')).reliability(bootstrap_iterations=10)
    assert r['reliability_status']=='UNOBSERVABLE'
    assert r['conservative_effective_sample_size']==0
    assert r['clustered_bootstrap']['win_rate_95'] is None


def test_clustered_ess_detects_shared_market_window(tmp_path):
    store=OutcomeInfrastructureStore(tmp_path/'x.db')
    for i in range(1,11):
        add_case(store,suffix=f'{i:02d}',confidence=70,gates=[],outcome='WIN' if i%2 else 'LOSS',realized_r=1 if i%2 else -1,symbol=f'S{i}USDT')
    r=OutcomeAnalyticsService(store).reliability(bootstrap_iterations=20)
    assert r['decisive_episode_count']==10
    assert r['market_event_cluster_count']==1
    assert r['temporal_cluster_ess']==1.0
    assert r['reliability_status']=='INSUFFICIENT'


def test_clustered_bootstrap_is_deterministic(tmp_path):
    store=OutcomeInfrastructureStore(tmp_path/'x.db')
    for i in range(1,5):
        cid=add_case(store,suffix=f'{i:02d}',confidence=70,gates=[],outcome='WIN' if i<3 else 'LOSS',realized_r=2 if i<3 else -1,symbol=f'S{i}USDT')
        with store.connect() as con:
            con.execute("update candidate_outcomes set outcome_time=? where candidate_id=?",(f'2026-07-20 {9+i:02d}:00:00',cid))
    svc=OutcomeAnalyticsService(store)
    assert svc.reliability(bootstrap_iterations=100,seed=7)==svc.reliability(bootstrap_iterations=100,seed=7)
    assert svc.reliability(bootstrap_iterations=100,seed=7)['clustered_bootstrap']['win_rate_95'] is not None


def test_snapshot_and_html_expose_reliability(tmp_path):
    svc=OutcomeAnalyticsService(OutcomeInfrastructureStore(tmp_path/'x.db'))
    assert 'statistical_reliability' in svc.snapshot()
    assert 'Statistical Reliability' in svc.render_html()
