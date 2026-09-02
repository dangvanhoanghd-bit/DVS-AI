from __future__ import annotations
import json, sqlite3
from pathlib import Path
from dvs_ai.services.outcome_infrastructure import OutcomeInfrastructureStore
from dvs_ai.services.quantum_dataset import QuantumDatasetFactory, QuantumReadinessState


def seed(tmp_path: Path, statuses):
    db=tmp_path/'paper.db'; store=OutcomeInfrastructureStore(db)
    with store.connect() as con:
        for i,status in enumerate(statuses):
            eid=f'e{i}'; cid=f'c{i}'; evalid=f'v{i}'; t=f'2026-01-01 00:{i%60:02d}:00'
            con.execute("INSERT INTO setup_episodes(setup_episode_id,symbol,direction,decision_engine_profile_hash,trade_plan_profile_hash,candidate_capture_profile_hash,setup_fingerprint,primary_zone_id,structural_event_id,lifecycle_family,status,started_at,last_seen_at,first_evaluation_id,activation_evaluation_id,evaluation_count,initial_gate_set,eventually_accepted,candidate_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid,'BTC/USDT','LONG','engine-hash','plan-hash','capture','fp'+str(i),1,'NONE','RETEST','OPEN',t,t,evalid,evalid,1,'[]',1,cid))
            con.execute("INSERT INTO episode_evaluations(setup_episode_id,evaluation_id,sequence_number,evaluated_at,entry_score,confidence,gate_set_json) VALUES(?,?,?,?,?,?,?)",(eid,evalid,1,t,70,75,'[]'))
            con.execute("INSERT INTO decision_candidates(candidate_id,setup_episode_id,activation_evaluation_id,activated_at,cohort,symbol,direction,decision_engine_profile_hash,trade_plan_profile_hash,entry_low,entry_high,planned_entry,invalidation,tp1,tp2,rr_planned,entry_wait_started_at,entry_expiry_at,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid,eid,evalid,t,'CENSUS','BTC/USDT','LONG','engine-hash','plan-hash',100,101,100.5,99,102,103,2,t,t,'FILLED',t))
            con.execute("INSERT INTO candidate_outcomes(outcome_id,candidate_id,resolver_profile_hash,status,outcome_time,realized_r,mfe_r,mae_r,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ('o'+str(i),cid,'resolver',status,t,1 if status=='WIN' else -1,1.2,-.5,t,t))
    allow=tmp_path/'allow.json'; allow.write_text(json.dumps({'schema_version':'dvs-policy-scope-v1','scope_name':'test','interacting_parameters':[]}),encoding='utf-8')
    return db,allow


def test_only_win_loss_are_research_episodes(tmp_path):
    db,allow=seed(tmp_path,['WIN','LOSS','AMBIGUOUS','EXPIRED_UNFILLED','PENDING'])
    r=QuantumDatasetFactory(db,allowed_parameters_path=allow,expected_decision_engine_checksum='engine-hash').build()
    assert r.decisive_count==2 and {x.outcome_status for x in r.episodes}=={'WIN','LOSS'}
    assert r.ambiguous_count==1 and r.expired_unfilled_count==1 and r.pending_count==1
    assert r.state==QuantumReadinessState.UNOBSERVABLE
    assert not r.optimizer_allowed and not r.recommendation_allowed and not r.shadow_apply_allowed


def test_wrong_engine_checksum_blocks_dataset(tmp_path):
    db,allow=seed(tmp_path,['WIN'])
    r=QuantumDatasetFactory(db,allowed_parameters_path=allow,expected_decision_engine_checksum='other').build()
    assert r.state==QuantumReadinessState.DATA_INTEGRITY_BLOCKED
    assert r.decisive_count==0


def test_read_only_source_and_sealed_export(tmp_path):
    db,allow=seed(tmp_path,['WIN','LOSS'])
    before=db.read_bytes()
    r=QuantumDatasetFactory(db,allowed_parameters_path=allow).build()
    ds,mf=r.export(tmp_path/'out')
    assert db.read_bytes()==before
    manifest=json.loads(mf.read_text(encoding='utf-8'))
    assert manifest['dataset_sha256'] and manifest['self_sha256']
    assert ds.exists()


def test_policy_scope_excludes_operational_settings(tmp_path):
    db,allow=seed(tmp_path,['WIN'])
    p=json.loads(allow.read_text()); p['operational_parameters_excluded']=['watchlist','scan_workers']; allow.write_text(json.dumps(p))
    r=QuantumDatasetFactory(db,allowed_parameters_path=allow).build()
    assert r.episodes[0].policy_scope_id.startswith('QPS-')


def test_missing_tables_is_integrity_blocked(tmp_path):
    db=tmp_path/'empty.db'; sqlite3.connect(db).close()
    r=QuantumDatasetFactory(db).build()
    assert r.state==QuantumReadinessState.DATA_INTEGRITY_BLOCKED
