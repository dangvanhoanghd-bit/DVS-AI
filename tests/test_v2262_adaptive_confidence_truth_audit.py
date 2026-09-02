import sqlite3
from dataclasses import replace

from dvs_ai.services.adaptive_confidence_service import AdaptiveConfidenceService
from dvs_ai.services.probability_calibration_service import ProbabilityCalibrationService


def _db(path, rows):
    with sqlite3.connect(path) as con:
        con.execute('''CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY, created_at TEXT, closed_at TEXT,
            confidence REAL, r_multiple REAL, direction TEXT, regime TEXT,
            status TEXT, result TEXT
        )''')
        con.executemany('''INSERT INTO paper_trades
            (created_at,closed_at,confidence,r_multiple,direction,regime,status,result)
            VALUES (?,?,?,?,?,?,?,?)''', rows)


def test_insufficient_context_keeps_global_probability(tmp_path):
    path = tmp_path/'paper.db'
    rows=[(str(i),str(i),70,1 if i%2 else -1,'LONG','TREND','CLOSED','WIN' if i%2 else 'LOSS') for i in range(20)]
    _db(path, rows)
    cal=ProbabilityCalibrationService(str(path), min_samples=80)
    svc=AdaptiveConfidenceService(str(path), min_context_samples=30)
    result=svc.adapt(base_probability=62, raw_confidence=70, direction='LONG', regime='TREND', calibrator=cal)
    assert result.state == 'INSUFFICIENT_CONTEXT'
    assert result.probability == 62
    assert result.adjustment == 0


def test_adjustment_is_bounded_and_observe_only(tmp_path):
    path=tmp_path/'paper.db'
    rows=[]
    # Chronological context remains strongly positive in train and holdout.
    for i in range(100):
        win = i % 5 != 0
        rows.append((f'{i:03}',f'{i:03}',70,1 if win else -1,'LONG','TREND','CLOSED','WIN' if win else 'LOSS'))
    _db(path, rows)
    cal=ProbabilityCalibrationService(str(path), min_samples=80, min_validation=20)
    model=cal.fit(force=True)
    assert model.validated
    base,_=cal.calibrate(70)
    svc=AdaptiveConfidenceService(str(path), min_context_samples=30, max_adjustment=8)
    result=svc.adapt(base_probability=base, raw_confidence=70, direction='LONG', regime='TREND', calibrator=cal)
    assert result.state in {'VALIDATED','REJECTED_VALIDATION'}
    assert abs(result.adjustment) <= 8
    # Service only returns annotation; it has no API for status/threshold/execution.
    assert not hasattr(svc, 'send_order')
    assert not hasattr(svc, 'position_size')


def test_nan_and_unknown_context_fail_safe(tmp_path):
    path=tmp_path/'paper.db'
    _db(path, [])
    cal=ProbabilityCalibrationService(str(path))
    svc=AdaptiveConfidenceService(str(path))
    result=svc.adapt(base_probability=float('nan'), raw_confidence=float('inf'), direction='', regime='', calibrator=cal)
    assert result.state == 'BASE_NOT_VALIDATED'
    assert result.probability == 0


def test_scanner_keeps_raw_confidence_gate_separate():
    source=open('dvs_ai/services/scanner.py', encoding='utf-8').read()
    assert 'adaptive_probability=adaptive.probability' in source
    assert 'confidence_score=adaptive.probability' not in source
    assert 'entry_status=adaptive' not in source
