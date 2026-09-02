import json
import sqlite3
from datetime import datetime, timedelta, timezone

from dvs_ai.services.evidence_reliability_service import EvidenceReliabilityService


def _db(path):
    with sqlite3.connect(path) as con:
        con.execute('''CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, direction TEXT, regime TEXT, r_multiple REAL,
            status TEXT, result TEXT, created_at TEXT, closed_at TEXT,
            evidence_snapshot_json TEXT
        )''')


def _add(path, *, n, family='ORDER_FLOW', wins=True, symbol='BTCUSDT', regime='TREND', score=80.0, age=0):
    now = datetime.now(timezone.utc)
    payload = json.dumps({family: {'score': score, 'quality': 1.0, 'available': True}})
    with sqlite3.connect(path) as con:
        for i in range(n):
            closed = (now - timedelta(days=age, minutes=i)).isoformat()
            con.execute('''INSERT INTO paper_trades
                (symbol,direction,regime,r_multiple,status,result,created_at,closed_at,evidence_snapshot_json)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                (symbol,'LONG',regime,1.0 if wins else -1.0,'CLOSED','WIN' if wins else 'LOSS',closed,closed,payload))


def test_insufficient_data_returns_unknown(tmp_path):
    db = tmp_path/'p.db'; _db(db); _add(db,n=5)
    svc=EvidenceReliabilityService(str(db), min_effective_samples=20)
    result=svc.evaluate(symbol='BTCUSDT',direction='LONG',regime='TREND')
    assert result['ORDER_FLOW'].state == 'UNKNOWN'
    assert result['ORDER_FLOW'].reliability == 0.0


def test_context_is_shrunk_not_extreme(tmp_path):
    db=tmp_path/'p.db'; _db(db)
    _add(db,n=30,wins=True,symbol='ETHUSDT')
    _add(db,n=10,wins=False,symbol='BTCUSDT')
    svc=EvidenceReliabilityService(str(db),min_effective_samples=5,prior_strength=12)
    item=svc.evaluate(symbol='BTCUSDT',direction='LONG',regime='TREND')['ORDER_FLOW']
    assert item.state in {'VALIDATED','SHRUNK'}
    assert 0.0 < item.reliability < 100.0


def test_old_samples_decay(tmp_path):
    db=tmp_path/'p.db'; _db(db)
    _add(db,n=25,wins=False,age=180)
    _add(db,n=25,wins=True,age=0)
    svc=EvidenceReliabilityService(str(db),min_effective_samples=5,half_life_days=30)
    item=svc.evaluate(symbol='BTCUSDT',direction='LONG',regime='TREND')['ORDER_FLOW']
    assert item.reliability > 60.0


def test_legacy_rows_without_snapshot_are_not_reverse_engineered(tmp_path):
    db=tmp_path/'p.db'; _db(db)
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO paper_trades(symbol,direction,regime,r_multiple,status,result,created_at,closed_at,evidence_snapshot_json) VALUES ('BTCUSDT','LONG','TREND',1,'CLOSED','WIN','2026-01-01','2026-01-01',NULL)")
    svc=EvidenceReliabilityService(str(db),min_effective_samples=5)
    assert svc.evaluate(symbol='BTCUSDT',direction='LONG',regime='TREND')['ORDER_FLOW'].state == 'UNKNOWN'
