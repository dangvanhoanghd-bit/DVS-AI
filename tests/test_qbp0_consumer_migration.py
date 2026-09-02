from __future__ import annotations

import json
import sqlite3

from dvs_ai.services.quantum_data_convergence import PaperTradeSource, QuantumDataAdapter
from dvs_ai.services.quantum_optimizer import QuantumOptimizer
from dvs_ai.services.quantum_readiness_service import QuantumReadinessService


def _snapshot() -> str:
    payload = {
        name: {"available": True, "score": 70.0, "quality": 1.0}
        for name in ("TIMING", "ENTRY", "ORDER_FLOW", "DIRECTION", "MARKET")
    }
    payload["_TRUTH"] = {
        "schema": "DVS_QUANTUM_TRAINING_V1",
        "calibration_state": "VALIDATED",
        "drift_state": "STABLE",
        "order_flow_quality": "FULL",
        "reliability_state": "STABLE",
    }
    return json.dumps(payload)


def _db(path) -> None:
    with sqlite3.connect(path) as con:
        con.execute("""CREATE TABLE paper_trades(
          id INTEGER PRIMARY KEY,created_at TEXT,closed_at TEXT,symbol TEXT,direction TEXT,
          status TEXT,result TEXT,r_multiple REAL,confidence REAL,entry_score REAL,
          risk_score REAL,rr_planned REAL,lab TEXT,pilot_id TEXT,regime TEXT,
          evidence_snapshot_json TEXT,setup_tags TEXT)""")
        con.executemany("INSERT INTO paper_trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
          (1,'2026-01-01','2026-01-02','BTCUSDT','LONG','CLOSED','TP2',1.5,70,65,20,2.0,'MAIN','p1','TREND',_snapshot(),'A'),
          (2,'2026-01-03','2026-01-04','ETHUSDT','SHORT','CLOSED','SL',-1.0,60,55,30,1.5,'SHADOW','p2','RANGE',_snapshot(),'B'),
          (3,'2026-01-05','2026-01-06','SOLUSDT','LONG','CLOSED','AMBIGUOUS',0.0,50,50,50,1.2,'SHADOW','p3','VOLATILE',_snapshot(),'C'),
        ])


def test_optimizer_consumes_adapter_without_direct_sql_dependency(tmp_path):
    db = tmp_path / 'paper.db'; _db(db)
    adapter = QuantumDataAdapter(PaperTradeSource(db))
    optimizer = QuantumOptimizer(db_path=db, config_path=tmp_path/'config.json', outcome_adapter=adapter)
    rows = optimizer._load_closed()
    assert [row.r_multiple for row in rows] == [1.5, -1.0]
    assert [row.setup_tags for row in rows] == ['A', 'B']
    assert optimizer._last_training_audit['total_closed'] == 2
    assert optimizer._last_training_audit['excluded_non_determinate'] == 1
    assert optimizer._last_training_audit['source_paper_trades'] == 2


def test_readiness_and_optimizer_share_same_adapter_truth_set(tmp_path):
    db = tmp_path / 'paper.db'; _db(db)
    adapter = QuantumDataAdapter(PaperTradeSource(db))
    optimizer = QuantumOptimizer(db_path=db, config_path=tmp_path/'config.json', outcome_adapter=adapter)
    readiness = QuantumReadinessService(db, outcome_adapter=adapter)
    optimizer_rows = optimizer._load_closed()
    snapshot = readiness.snapshot()
    assert snapshot.total_closed == optimizer._last_training_audit['total_closed'] == 2
    assert snapshot.eligible == optimizer._last_training_audit['eligible'] == len(optimizer_rows) == 2
    metrics = {item.key: item.current for item in snapshot.metrics}
    assert metrics['long'] == 1
    assert metrics['short'] == 1
    assert metrics['trend'] == 1
    assert metrics['range'] == 1


def test_missing_database_preserves_fail_closed_empty_behavior(tmp_path):
    missing = tmp_path / 'missing.db'
    optimizer = QuantumOptimizer(db_path=missing, config_path=tmp_path/'config.json')
    readiness = QuantumReadinessService(missing)
    assert optimizer._load_closed() == []
    assert readiness.snapshot().eligible == 0
