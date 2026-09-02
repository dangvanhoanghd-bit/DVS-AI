from pathlib import Path
import json
import sqlite3

from dvs_ai.services.quantum_optimizer import QuantumOptimizer

ROOT=Path(__file__).parents[1]

def seed(path,count=90):
    with sqlite3.connect(path) as con:
        con.execute("""CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY, created_at TEXT, lab TEXT, status TEXT,
            result TEXT, confidence REAL, entry_score REAL, risk_score REAL,
            rr_planned REAL, r_multiple REAL, setup_tags TEXT, evidence_snapshot_json TEXT)""")
        for i in range(count):
            win=i%3==0
            con.execute("INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(
                i+1,f"2026-01-{1+(i//24)%28:02d} {i%24:02d}:00:00",
                "SHADOW","CLOSED","TP2" if win else "STOP",
                55+(i%10),52+(i%12),35+(i%20),1.4+(i%5)*0.1,
                1.2 if win else -1.0,"TREND_EARLY_FORMATION",
                json.dumps({'TIMING':{'score':70,'quality':1,'available':True},'ENTRY':{'score':70,'quality':1,'available':True},'ORDER_FLOW':{'score':70,'quality':1,'available':True},'DIRECTION':{'score':70,'quality':1,'available':True},'MARKET':{'score':70,'quality':1,'available':True},'_TRUTH':{'schema':'DVS_QUANTUM_TRAINING_V1','calibration_state':'VALIDATED','drift_state':'STABLE','order_flow_quality':'FULL','evidence_reliability_state':'VALIDATED'}}),
            ))

def config(path):
    path.write_text(json.dumps({
        "main_confidence":68,"main_entry":62,"main_risk_max":50,"main_rr_min":1.8,
        "shadow_confidence":45,"shadow_entry":45,"shadow_risk_max":65,"shadow_rr_min":1.4,
    }),encoding="utf-8")

def test_progress_and_bounded_cache(tmp_path):
    db=tmp_path/"paper.db"; cfg=tmp_path/"config.json"
    seed(db); config(cfg)
    progress=[]
    opt=QuantumOptimizer(str(db),str(cfg),population_size=20,generations=10,min_closed=80,fitness_cache_size=60)
    report=opt.optimize(progress_callback=progress.append)
    assert len(progress)==10
    assert report["fitness_cache_peak"]<=60
    assert len(report["generation_history"])==10
    assert len(opt._fitness_cache)==0

def test_cancel_between_generations(tmp_path):
    db=tmp_path/"paper.db"; cfg=tmp_path/"config.json"
    seed(db); config(cfg)
    calls={"n":0}
    def cancel():
        calls["n"]+=1
        return calls["n"]>2
    opt=QuantumOptimizer(str(db),str(cfg),population_size=20,generations=10,min_closed=80)
    report=opt.optimize(cancel_check=cancel)
    assert report["status"]=="CANCELLED"
    assert len(opt._fitness_cache)==0

def test_dedicated_optimizer_tab_and_thread():
    source=(ROOT/"dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    assert "class QuantumWorker" in source
    assert "def _build_quantum_optimizer_tab" in source
    assert 'self.tabs.addTab(tab,"Quantum Optimizer")' in source
    assert "moveToThread" in source
    assert "quantum_fitness_chart" in source
