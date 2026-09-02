import sqlite3
from dataclasses import replace
from pathlib import Path

from dvs_ai.services.probability_calibration_service import ProbabilityCalibrationService


def make_db(path: Path, rows):
    with sqlite3.connect(path) as con:
        con.execute('''CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT, closed_at TEXT, status TEXT, result TEXT,
            confidence REAL, r_multiple REAL
        )''')
        for i, (confidence, win) in enumerate(rows):
            con.execute('''INSERT INTO paper_trades
                (created_at,closed_at,status,result,confidence,r_multiple)
                VALUES (?,?,?,?,?,?)''', (
                f'2026-01-{1+i//24:02d} {i%24:02d}:00:00',
                f'2026-01-{1+i//24:02d} {i%24:02d}:30:00',
                'CLOSED', 'TP2' if win else 'STOP', confidence,
                1.5 if win else -1.0,
            ))


def test_insufficient_data_fails_closed(tmp_path):
    db = tmp_path/'paper.db'
    make_db(db, [(70, True)] * 20)
    service = ProbabilityCalibrationService(str(db), min_samples=80)
    probability, model = service.calibrate(70)
    assert probability == 0.0
    assert model.state == 'INSUFFICIENT_DATA'


def test_monotonic_calibration_and_chronological_validation(tmp_path):
    db = tmp_path/'paper.db'
    rows = []
    for i in range(160):
        confidence = [45, 55, 65, 75, 85, 95][i % 6]
        threshold = {45: 0.30, 55: 0.42, 65: 0.52, 75: 0.62, 85: 0.72, 95: 0.82}[confidence]
        win = ((i * 37) % 100) / 100.0 < threshold
        rows.append((confidence, win))
    make_db(db, rows)
    service = ProbabilityCalibrationService(str(db), min_samples=80)
    model = service.fit()
    assert model.state == 'VALIDATED'
    probabilities = [b.calibrated_probability for b in model.bins]
    assert probabilities == sorted(probabilities)
    assert model.validation_samples >= 20
    assert model.calibrated_brier <= model.raw_brier + 0.005


def test_duplicate_confidence_is_not_claimed_as_probability_without_validation(tmp_path):
    db = tmp_path/'paper.db'
    rows = [(95, i % 5 == 0) for i in range(100)]
    make_db(db, rows)
    service = ProbabilityCalibrationService(str(db), min_samples=80)
    probability, model = service.calibrate(95)
    if model.state != 'VALIDATED':
        assert probability == 0.0


def test_no_execution_dependency():
    source = Path('dvs_ai/services/probability_calibration_service.py').read_text()
    forbidden = ('TradeIntent', 'PositionSizer', 'send_order', 'create_order', 'Execution')
    assert not any(token in source for token in forbidden)
