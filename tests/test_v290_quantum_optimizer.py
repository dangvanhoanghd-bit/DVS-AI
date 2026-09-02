import json
import sqlite3
from pathlib import Path

from dvs_ai.services.quantum_optimizer import QuantumOptimizer


def seed_db(path: Path, count: int = 120):
    with sqlite3.connect(path) as con:
        con.execute("""CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY, created_at TEXT, lab TEXT, status TEXT,
            result TEXT, confidence REAL, entry_score REAL, risk_score REAL,
            rr_planned REAL, r_multiple REAL, setup_tags TEXT, evidence_snapshot_json TEXT)""")
        for i in range(count):
            good = i % 3 != 0
            con.execute("INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(
                i+1,f"2026-01-{1+i//24:02d} {i%24:02d}:00:00",'SHADOW','CLOSED','TP2' if good else 'STOP',
                58 if good else 43,57 if good else 42,35 if good else 60,1.8 if good else 1.2,
                1.2 if good else -1.0,'TREND_EARLY_FORMATION' if good else 'TREND_LATE_TREND',
                json.dumps({'TIMING':{'score':70,'quality':1,'available':True},'ENTRY':{'score':70,'quality':1,'available':True},'ORDER_FLOW':{'score':70,'quality':1,'available':True},'DIRECTION':{'score':70,'quality':1,'available':True},'MARKET':{'score':70,'quality':1,'available':True},'_TRUTH':{'schema':'DVS_QUANTUM_TRAINING_V1','calibration_state':'VALIDATED','drift_state':'STABLE','order_flow_quality':'FULL','evidence_reliability_state':'VALIDATED'}})))


def test_optimizer_uses_real_closed_trades(tmp_path):
    db=tmp_path/'paper.db'; seed_db(db)
    cfg=tmp_path/'config.json'; cfg.write_text(json.dumps({
        'main_confidence':68,'main_entry':62,'main_risk_max':50,'main_rr_min':1.8,
        'shadow_confidence':45,'shadow_entry':45,'shadow_risk_max':65,'shadow_rr_min':1.4}),encoding='utf-8')
    opt=QuantumOptimizer(str(db),str(cfg),population_size=20,generations=10,min_closed=80)
    report=opt.optimize()
    assert report['closed']==120
    assert report['status'] in ('RECOMMENDATION','NO_STABLE_IMPROVEMENT')
    assert report['validation_count']>0
    assert 'best_params' in report


def test_insufficient_data_is_safe(tmp_path):
    db=tmp_path/'paper.db'; seed_db(db,20)
    cfg=tmp_path/'config.json'; cfg.write_text('{}',encoding='utf-8')
    report=QuantumOptimizer(str(db),str(cfg),min_closed=80).optimize()
    assert report['status']=='INSUFFICIENT_QUALITY_DATA'


def test_shadow_apply_has_guardrails_and_backup(tmp_path):
    cfg=tmp_path/'config.json'; cfg.write_text(json.dumps({
        'shadow_confidence':45,'shadow_entry':45,'shadow_risk_max':65,'shadow_rr_min':1.4}),encoding='utf-8')
    opt=QuantumOptimizer(str(tmp_path/'none.db'),str(cfg))
    report={'safe_to_apply_shadow':True,'best_params':{
        'shadow_confidence':55,'shadow_entry':55,'shadow_risk_max':75,'shadow_rr_min':1.8}}
    candidate=opt.create_shadow_candidate(report, str(tmp_path/'shadow_candidate.json'))
    raw=json.loads(cfg.read_text(encoding='utf-8'))
    assert raw['shadow_confidence']==45
    assert raw['shadow_rr_min']==1.4
    assert candidate['candidate']['shadow_confidence']==47.0
    assert candidate['candidate']['shadow_rr_min']==1.5
    assert candidate['human_approval_required'] is True
