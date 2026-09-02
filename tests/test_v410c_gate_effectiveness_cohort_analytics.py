from __future__ import annotations

import json
from dvs_ai.services.outcome_analytics import OutcomeAnalyticsService
from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore
from dvs_ai.services.setup_episode_service import EvaluationCapture, SetupEpisodeService


def add_case(store, *, suffix, confidence, gates, outcome, realized_r, direction='LONG', symbol='BTCUSDT'):
    svc=SetupEpisodeService(store)
    ts=f'2026-07-20 10:{int(suffix):02d}:00'
    _,cid=svc.capture(EvaluationCapture(
        symbol=symbol,direction=direction,evaluated_at=ts,entry_score=60,
        confidence=confidence,opportunity_score=55,gate_set=tuple(gates),
        decision_engine_profile_hash=('d'*63)+str(int(suffix)%10),
        level=100+int(suffix),atr_15m=2,lifecycle='EARLY_FORMATION',
        entry_low=99,entry_high=100,invalidation=98,tp1=102,tp2=104,
        evaluation_id=f'e{suffix}'))
    with store.connect() as con:
        con.execute('update candidate_outcomes set status=?,realized_r=? where candidate_id=?',(outcome,realized_r,cid))
        con.execute('update decision_candidates set status=? where candidate_id=?',(outcome,cid))
    return cid


def test_gate_confusion_matrix_is_episode_level(tmp_path):
    store=OutcomeInfrastructureStore(tmp_path/'p.db')
    add_case(store,suffix='01',confidence=40,gates=['CONFIDENCE_LT_68'],outcome='LOSS',realized_r=-1)
    add_case(store,suffix='02',confidence=45,gates=['CONFIDENCE_LT_68'],outcome='WIN',realized_r=3)
    add_case(store,suffix='03',confidence=80,gates=[],outcome='WIN',realized_r=2)
    add_case(store,suffix='04',confidence=85,gates=[],outcome='LOSS',realized_r=-1)
    metric=OutcomeAnalyticsService(store).gate_effectiveness()[0]
    assert metric.true_rejection == 1
    assert metric.false_rejection == 1
    assert metric.true_acceptance == 1
    assert metric.false_acceptance == 1
    assert metric.rejection_precision == .5
    assert metric.false_rejection_rate == .5


def test_calibration_excludes_ambiguous_and_unfilled(tmp_path):
    store=OutcomeInfrastructureStore(tmp_path/'p.db')
    add_case(store,suffix='01',confidence=72,gates=[],outcome='WIN',realized_r=2)
    add_case(store,suffix='02',confidence=78,gates=[],outcome='LOSS',realized_r=-1)
    add_case(store,suffix='03',confidence=75,gates=[],outcome='AMBIGUOUS',realized_r=None)
    bucket=[x for x in OutcomeAnalyticsService(store).calibration() if x.lower==70][0]
    assert bucket.samples == 2 and bucket.actual_win_rate == .5
    assert bucket.average_realized_r == .5


def test_snapshot_discloses_statistical_boundary(tmp_path):
    store=OutcomeInfrastructureStore(tmp_path/'p.db')
    add_case(store,suffix='01',confidence=72,gates=[],outcome='WIN',realized_r=2)
    payload=OutcomeAnalyticsService(store).snapshot()
    assert payload['statistical_unit']=='SETUP_EPISODE'
    assert 'cross_symbol_dependence' in payload['known_limitations']
    assert payload['safety_boundary']['decision_engine_frozen'] is True
    assert payload['safety_boundary']['automatic_tuning'] is False


def test_exports_json_and_html(tmp_path):
    store=OutcomeInfrastructureStore(tmp_path/'p.db')
    add_case(store,suffix='01',confidence=72,gates=[],outcome='WIN',realized_r=2)
    service=OutcomeAnalyticsService(store)
    jp=service.export_json(tmp_path/'report.json'); hp=service.export_html(tmp_path/'report.html')
    assert json.loads(jp.read_text())['episode_count']==1
    text=hp.read_text(encoding='utf-8')
    assert 'Gate Effectiveness' in text and 'Cross-Symbol Dependence' in text
