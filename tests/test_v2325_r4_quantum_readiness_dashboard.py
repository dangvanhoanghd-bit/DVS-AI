from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from dvs_ai.services.quantum_readiness_service import QuantumReadinessService
from dvs_ai.services.quantum_report_contract import build_quantum_report_view


def _snapshot(calibration="VALIDATED", drift="STABLE", quality="FULL"):
    payload = {
        name: {"available": True, "score": 60.0, "quality": 1.0}
        for name in ("TIMING", "ENTRY", "ORDER_FLOW", "DIRECTION", "MARKET")
    }
    payload["_TRUTH"] = {
        "schema": "DVS_QUANTUM_TRAINING_V1",
        "calibration_state": calibration,
        "drift_state": drift,
        "order_flow_quality": quality,
        "reliability_state": "STABLE",
    }
    return json.dumps(payload)


def _db(path: Path):
    con = sqlite3.connect(path)
    con.execute("""
        CREATE TABLE paper_trades (
          id INTEGER PRIMARY KEY, created_at TEXT, status TEXT, result TEXT,
          direction TEXT, regime TEXT, evidence_snapshot_json TEXT
        )
    """)
    return con


def test_readiness_counts_only_truth_qualified_closed_rows(tmp_path):
    path = tmp_path / "paper.db"
    with _db(path) as con:
        rows = [
            (1, "2026-07-01T00:00:00+00:00", "CLOSED", "TP2", "LONG", "TREND", _snapshot()),
            (2, "2026-07-02T00:00:00+00:00", "CLOSED", "SL", "SHORT", "RANGE", _snapshot(calibration="WATCH")),
            (3, "2026-07-03T00:00:00+00:00", "ACTIVE", "OPEN", "LONG", "TREND", _snapshot()),
        ]
        con.executemany("INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?)", rows)
    snap = QuantumReadinessService(path, required=80).snapshot()
    assert snap.total_closed == 2
    assert snap.eligible == 1
    assert snap.audit["excluded_calibration"] == 1
    by_key = {m.key: m for m in snap.metrics}
    assert by_key["long"].current == 1
    assert by_key["short"].current == 0
    assert by_key["trend"].current == 1


def test_eta_is_unknown_for_short_or_sparse_history(tmp_path):
    path = tmp_path / "paper.db"
    with _db(path) as con:
        for i in range(1, 10):
            con.execute(
                "INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?)",
                (i, f"2026-07-01T00:00:0{i}+00:00", "CLOSED", "TP2", "LONG", "TREND", _snapshot()),
            )
    snap = QuantumReadinessService(path).snapshot()
    assert snap.velocity_per_day is None
    assert snap.eta_days is None
    assert not snap.eta_reliable


def test_eta_requires_at_least_ten_samples_and_one_day_span(tmp_path):
    path = tmp_path / "paper.db"
    with _db(path) as con:
        for i in range(10):
            con.execute(
                "INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?)",
                (i + 1, f"2026-07-{i+1:02d}T00:00:00+00:00", "CLOSED", "TP2", "LONG", "TREND", _snapshot()),
            )
    snap = QuantumReadinessService(path, required=80).snapshot()
    assert snap.eta_reliable
    assert snap.velocity_per_day is not None and snap.velocity_per_day > 0
    assert snap.eta_days is not None and snap.eta_days > 0


def test_insufficient_quality_data_is_valid_fail_closed_report():
    view = build_quantum_report_view({
        "status": "INSUFFICIENT_QUALITY_DATA",
        "closed": 0,
        "total_closed": 15,
        "required": 80,
        "training_audit": {"excluded_calibration": 15},
    })
    assert view.schema_valid
    assert not view.safe_to_apply_shadow
    assert view.status == "INSUFFICIENT_QUALITY_DATA"
    assert "0/80" in view.text
    assert "calibration" in view.text.lower()


def test_main_window_contains_both_readiness_dashboards():
    source = Path(__file__).parents[1] / "dvs_ai" / "ui" / "main_window.py"
    text = source.read_text(encoding="utf-8")
    assert "learning_quantum_readiness" in text
    assert "quantum_dashboard_readiness" in text
    assert "QuantumReadinessService" in text
