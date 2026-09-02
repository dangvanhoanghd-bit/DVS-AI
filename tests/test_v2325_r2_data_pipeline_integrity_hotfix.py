from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from dvs_ai.services.shadow_observation_service import ShadowObservationStore, ShadowObservationRuntime
from dvs_ai.services.paper_trade_service import PaperTradeService


def payload(created_at="2026-07-17T04:34:09+00:00"):
    return dict(
        candidate_id="CURRENT_SHADOW_BASELINE",
        symbol="1000BONK/USDT:USDT",
        direction="SHORT",
        regime="TREND",
        baseline_decision="WAIT",
        shadow_decision="WAIT",
        baseline_score=32.892412442590896,
        shadow_score=32.892412442590896,
        truth={"schema":"DVS_SHADOW_OBSERVATION_V1", "generated_at": created_at},
        created_at=created_at,
    )


def test_append_is_idempotent(tmp_path: Path):
    store = ShadowObservationStore(str(tmp_path / "paper.db"))
    first = store.append_with_status(**payload(), idempotency_key="scan-1")
    second = store.append_with_status(**payload(), idempotency_key="scan-1")
    assert first.created and not first.deduplicated
    assert not second.created and second.deduplicated
    assert first.observation_id == second.observation_id
    with sqlite3.connect(tmp_path / "paper.db") as conn:
        assert conn.execute("select count(*) from shadow_observations").fetchone()[0] == 1


def test_runtime_counts_deduplicated(tmp_path: Path):
    store = ShadowObservationStore(str(tmp_path / "paper.db"))
    runtime = ShadowObservationRuntime(store=store, data_dir=str(tmp_path), promotion_dir=str(tmp_path / "promotions"))
    a = SimpleNamespace(
        confidence_score=40.0,
        smart_entry=SimpleNamespace(entry_score=42.0),
        generated_at="2026-07-17T04:34:09+00:00",
        symbol="BTC/USDT:USDT",
        regime=SimpleNamespace(regime="TREND"),
        probability_calibration_state="NOT_EVALUATED",
        calibration_drift_state="INSUFFICIENT_DATA",
        evidence_reliability_summary=(), calibrated_probability=0.0,
        adaptive_probability=0.0, evidence_reliability_score=0.0,
    )
    x = runtime.record_pair(a, direction="LONG", main_ok=False, shadow_ok=False)
    y = runtime.record_pair(a, direction="LONG", main_ok=False, shadow_ok=False)
    assert x == y
    d = runtime.diagnostics()
    assert d["attempted"] == 2
    assert d["recorded"] == 1
    assert d["deduplicated"] == 1


def test_existing_duplicates_are_archived_and_merged(tmp_path: Path):
    db = tmp_path / "paper.db"
    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE shadow_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                candidate_id TEXT NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL,
                regime TEXT NOT NULL, baseline_decision TEXT NOT NULL, shadow_decision TEXT NOT NULL,
                baseline_score REAL NOT NULL, shadow_score REAL NOT NULL, paper_trade_id INTEGER,
                outcome_r REAL, outcome_result TEXT, closed_at TEXT, truth_json TEXT NOT NULL
            )
        """)
        p = payload(); truth=json.dumps(p["truth"], sort_keys=True)
        values=(p["created_at"],p["candidate_id"],p["symbol"],p["direction"],p["regime"],
                p["baseline_decision"],p["shadow_decision"],p["baseline_score"],p["shadow_score"])
        conn.execute("insert into shadow_observations values (NULL,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,?)", values+(truth,))
        conn.execute("insert into shadow_observations values (NULL,?,?,?,?,?,?,?,?,?,7,1.5,'TP2','2026-07-17T05:00:00+00:00',?)", values+(truth,))
        conn.execute("insert into shadow_observations values (NULL,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,?)", values+(truth,))
    ShadowObservationStore(str(db))
    with sqlite3.connect(db) as conn:
        rows=conn.execute("select paper_trade_id,outcome_r,outcome_result from shadow_observations").fetchall()
        archived=conn.execute("select count(*) from shadow_observation_duplicate_archive").fetchone()[0]
    assert rows == [(7, 1.5, "TP2")]
    assert archived == 2


def test_observation_key_unique_index_exists(tmp_path: Path):
    store=ShadowObservationStore(str(tmp_path/"paper.db"))
    with sqlite3.connect(store.db_path) as conn:
        indexes={row[1] for row in conn.execute("pragma index_list(shadow_observations)")}
    assert "idx_shadow_observation_key" in indexes


def test_paper_diagnostics_expose_zero_evaluated(tmp_path: Path):
    service = object.__new__(PaperTradeService)
    service.db_path = tmp_path / "paper.db"
    service._diagnostics = {"evaluated":0,"main_eligible":0,"shadow_eligible":0,"created":0,
                            "duplicate_blocked":0,"capacity_blocked":0,"gate_blocked":0,
                            "invalid_direction":0,"errors":0}
    with sqlite3.connect(service.db_path) as conn:
        conn.execute("create table paper_trades(id integer primary key, created_at text, status text)")
    d=PaperTradeService.diagnostics(service)
    assert d["evaluated"] == 0
    assert d["last_trade_created_at"] is None
    assert Path(d["db_path"]).is_absolute()


def test_truth_dashboard_no_owned_item_reinsert_pattern():
    root=Path(__file__).resolve().parents[1]
    text=(root/"dvs_ai/ui/truth_dashboard.py").read_text(encoding="utf-8")
    assert ".item(row, col) or QTableWidgetItem()" not in text
    assert ".item(row,col) or QTableWidgetItem()" not in text
