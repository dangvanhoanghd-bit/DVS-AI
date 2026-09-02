from __future__ import annotations

import sqlite3
from pathlib import Path

from dvs_ai.services.quantum_report_contract import build_quantum_report_view
from dvs_ai.services.shadow_observation_service import ShadowObservationStore, ShadowObservationRuntime


def test_quantum_partial_report_is_fail_closed_not_keyerror():
    view = build_quantum_report_view({"status": "NO_STABLE_IMPROVEMENT", "reason": "early exit"})
    assert view.status == "SCHEMA_MISMATCH"
    assert view.safe_to_apply_shadow is False
    assert "base_validation" in view.missing_keys


def test_quantum_insufficient_data_contract():
    view = build_quantum_report_view({"status": "INSUFFICIENT_DATA", "closed": 15, "required": 80})
    assert view.schema_valid is True
    assert view.safe_to_apply_shadow is False
    assert "15/80" in view.text


def test_quantum_success_contract_enables_only_explicit_safe_flag():
    report = {
        "status": "RECOMMENDATION", "train_count": 80, "validation_count": 40,
        "base_validation": {"wr": 40, "avg_r": 0.1, "pf": 1.2, "n": 30},
        "optimized_validation": {"wr": 50, "avg_r": 0.2, "pf": 1.4, "n": 31},
        "best_params": {"shadow_confidence": 55, "shadow_entry": 50, "shadow_risk_max": 60, "shadow_rr_min": 1.5},
        "safe_to_apply_shadow": True,
    }
    view = build_quantum_report_view(report)
    assert view.schema_valid is True
    assert view.safe_to_apply_shadow is True


def test_shadow_store_migrates_schema_and_exposes_absolute_path(tmp_path):
    db = tmp_path / "paper.db"
    with sqlite3.connect(db) as con:
        con.execute("""CREATE TABLE shadow_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, candidate_id TEXT NOT NULL,
            symbol TEXT NOT NULL, direction TEXT NOT NULL, regime TEXT NOT NULL,
            baseline_decision TEXT NOT NULL, shadow_decision TEXT NOT NULL,
            baseline_score REAL NOT NULL, shadow_score REAL NOT NULL, paper_trade_id INTEGER,
            outcome_r REAL, outcome_result TEXT, closed_at TEXT, truth_json TEXT NOT NULL)""")
    store = ShadowObservationStore(str(db))
    diag = store.schema_diagnostics()
    assert diag["observation_key_column"] is True
    assert diag["unique_index"] is True
    assert Path(diag["db_path"]) == db.resolve()


def test_runtime_diagnostics_include_store_schema(tmp_path):
    store = ShadowObservationStore(str(tmp_path / "paper.db"))
    runtime = ShadowObservationRuntime(store=store, data_dir=str(tmp_path), promotion_dir=str(tmp_path / "promotions"))
    diag = runtime.diagnostics()
    assert diag["store_schema"]["unique_index"] is True
    assert diag["store_schema"]["timestamp_storage"].startswith("UTC")
