from datetime import datetime,timezone,timedelta
from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore
from dvs_ai.services.episode_integrity_monitor import EpisodeIntegrityMonitor

def test_empty_canonical_schema_is_healthy(tmp_path):
    db=tmp_path/'x.db'; OutcomeInfrastructureStore(db)
    s=EpisodeIntegrityMonitor(db).snapshot()
    assert s['status']=='HEALTHY' and s['issue_count']==0

def test_detects_missing_trace_sequence_and_stale_episode(tmp_path):
    db=tmp_path/'x.db'; st=OutcomeInfrastructureStore(db)
    old=(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
    with st.connect() as c:
        c.execute("INSERT INTO setup_episodes(setup_episode_id,symbol,direction,decision_engine_profile_hash,trade_plan_profile_hash,candidate_capture_profile_hash,setup_fingerprint,primary_zone_id,structural_event_id,lifecycle_family,status,started_at,last_seen_at,first_evaluation_id,evaluation_count,initial_gate_set,episode_class) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('e','BTCUSDT','LONG','d','t','c','f',1,'NONE','L','OPEN',old,old,'v',2,'[]','CENSUS'))
        c.execute("INSERT INTO episode_evaluations(setup_episode_id,evaluation_id,sequence_number,evaluated_at,entry_score,confidence,gate_set_json) VALUES(?,?,?,?,?,?,?)",('e','v',2,old,1,1,'[]'))
    s=EpisodeIntegrityMonitor(db).snapshot()
    codes={i['code'] for i in s['issues']}
    assert {'MISSING_DIAGNOSTIC_TRACE','SEQUENCE_GAP','EVALUATION_COUNT_MISMATCH','STALE_OPEN_EPISODE'} <= codes
    assert s['status']=='DEGRADED'
