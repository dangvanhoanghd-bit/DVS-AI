import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from dvs_ai.services.calibration_drift_monitor import CalibrationDriftMonitor


def _db(path: Path, rows):
    with sqlite3.connect(path) as con:
        con.execute('''CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY, confidence REAL, r_multiple REAL,
            status TEXT, result TEXT, created_at TEXT, closed_at TEXT
        )''')
        con.executemany(
            '''INSERT INTO paper_trades
               (id, confidence, r_multiple, status, result, created_at, closed_at)
               VALUES (?,?,?,?,?,?,?)''',
            [
                (i + 1, c, r, 'CLOSED', 'WIN' if r > 0 else 'LOSS',
                 (datetime(2026, 1, 1) + timedelta(hours=i)).isoformat(sep=' '),
                 (datetime(2026, 1, 1) + timedelta(hours=i, minutes=30)).isoformat(sep=' '))
                for i, (c, r) in enumerate(rows)
            ],
        )


def test_insufficient_data_fails_closed(tmp_path):
    path = tmp_path / 'paper.db'
    _db(path, [(70.0, 1.0)] * 50)
    report = CalibrationDriftMonitor(str(path)).evaluate()
    assert report.state == 'INSUFFICIENT_DATA'
    assert report.reference_samples == 0


def test_stable_distribution_remains_stable(tmp_path):
    path = tmp_path / 'paper.db'
    rows = []
    for i in range(160):
        confidence = 70.0 + (i % 5)
        outcome = 1.0 if i % 10 < 7 else -1.0
        rows.append((confidence, outcome))
    _db(path, rows)
    report = CalibrationDriftMonitor(str(path), recent_window=40).evaluate()
    assert report.state == 'STABLE'
    assert report.recent_samples == 40


def test_recent_failure_and_distribution_shift_raise_drift(tmp_path):
    path = tmp_path / 'paper.db'
    reference = [(65.0 + (i % 8), 1.0 if i % 10 < 7 else -1.0) for i in range(120)]
    recent = [(95.0, -1.0) for _ in range(40)]
    _db(path, reference + recent)
    report = CalibrationDriftMonitor(str(path), recent_window=40).evaluate()
    assert report.state == 'DRIFT'
    assert report.recent_brier > report.reference_brier
    assert report.confidence_psi >= 0.25


def test_monitor_is_observe_only():
    source = Path('dvs_ai/services/calibration_drift_monitor.py').read_text()
    forbidden = ('TradeIntent', 'PositionSizer', 'send_order', 'confidence_score =', 'entry_status =')
    for token in forbidden:
        assert token not in source
