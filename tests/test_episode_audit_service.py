import sqlite3
from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore
from dvs_ai.services.episode_audit_service import EpisodeAuditService


def test_episode_audit_empty(tmp_path):
    db=tmp_path/'x.db'; OutcomeInfrastructureStore(db)
    service=EpisodeAuditService(db)
    assert service.list_episodes()==[]
    assert service.episode_detail('missing')['episode'] is None


def test_episode_audit_reads_trace_and_timeline(tmp_path):
    db=tmp_path/'x.db'; store=OutcomeInfrastructureStore(db)
    with store.connect() as con:
        con.execute("INSERT INTO setup_episodes(setup_episode_id,symbol,direction,decision_engine_profile_hash,trade_plan_profile_hash,candidate_capture_profile_hash,setup_fingerprint,primary_zone_id,structural_event_id,lifecycle_family,status,started_at,last_seen_at,first_evaluation_id,evaluation_count,initial_gate_set) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('ep','BTC/USDT','LONG','d','p','c','f',1,'NONE','FORMING','OPEN','2026-01-01 00:00:00','2026-01-01 00:01:00','ev',1,'[]'))
        con.execute("INSERT INTO episode_evaluations VALUES(?,?,?,?,?,?,?,?,?)",('ep','ev',1,'2026-01-01 00:00:00',25,30,40,'[\"G1\"]',1.0))
    store.record_diagnostic_trace(evaluation_id='ev',episode_id='ep',decision_hash='d',trace={'scores':{'trend':12}})
    detail=EpisodeAuditService(db).episode_detail('ep')
    assert detail['episode']['symbol']=='BTC/USDT'
    assert detail['evaluations'][0]['trace']['scores']['trend']==12
    assert detail['timeline'][0]['kind']=='EPISODE_STARTED'
