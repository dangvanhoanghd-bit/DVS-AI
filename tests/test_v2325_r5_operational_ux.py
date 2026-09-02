from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from dvs_ai.services.operational_journey_service import OperationalJourneyService


def _build_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.execute("""CREATE TABLE paper_trades(
            id INTEGER PRIMARY KEY, status TEXT, direction TEXT, closed_at TEXT,
            quality_snapshot_json TEXT
        )""")
        con.execute("""CREATE TABLE shadow_observations(
            id INTEGER PRIMARY KEY, closed_at TEXT
        )""")
        con.execute("""CREATE TABLE ai_health_history(
            id INTEGER PRIMARY KEY, generated_at TEXT, score REAL, state TEXT,
            contributors_json TEXT, alerts_json TEXT, snapshot_key TEXT UNIQUE
        )""")
        con.executemany(
            "INSERT INTO ai_health_history VALUES(?,?,?,?,?,?,?)",
            [
                (1, "2026-07-17T00:00:00+00:00", 28.0, "CRITICAL", "{}", "[]", "a"),
                (2, "2026-07-17T01:00:00+00:00", 42.0, "WATCH", "{}", "[]", "b"),
            ],
        )
        con.executemany(
            "INSERT INTO shadow_observations VALUES(?,?)",
            [(1, "2026-07-17T00:30:00+00:00"), (2, "2026-07-17T01:30:00+00:00")],
        )


def test_journey_history_is_observe_only_and_chronological(tmp_path: Path):
    db = tmp_path / "paper.db"
    _build_db(db)
    snapshot = OperationalJourneyService(str(db), quantum_required=80).snapshot()
    assert [row["score"] for row in snapshot.health_history] == [28.0, 42.0]
    assert [row["outcomes"] for row in snapshot.evidence_history] == [1, 2]
    assert snapshot.stages[-1].state == "IMMUTABLE"


def test_learning_card_explains_closed_total_and_open():
    source = Path("dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
    assert "Tổng PAPER" in source
    assert "đang mở" in source
    assert "đủ chuẩn Quantum" in source


def test_truth_dashboard_distinguishes_learning_from_critical():
    source = Path("dvs_ai/ui/truth_dashboard.py").read_text(encoding="utf-8")
    assert 'display_state = "LEARNING" if learning_only else health.state' in source
    assert 'obs_state = "COLLECTING EVIDENCE"' in source
    assert 'obs_state = "QUALITY GATE WAITING"' in source


def test_truth_dashboard_contains_journey_and_history_charts():
    source = Path("dvs_ai/ui/truth_dashboard.py").read_text(encoding="utf-8")
    assert "AI Journey & Operational History" in source
    assert "AI Health History" in source
    assert "Evidence Outcome Accumulation" in source
