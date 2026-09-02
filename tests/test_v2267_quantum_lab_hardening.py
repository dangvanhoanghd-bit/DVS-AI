import json
import sqlite3
from pathlib import Path

import pytest

from dvs_ai.services.quantum_optimizer import QuantumOptimizer


def snapshot(calibration="VALIDATED", drift="STABLE", quality="FULL"):
    return json.dumps({
        "TIMING": {"score": 70, "quality": 1, "available": True},
        "ENTRY": {"score": 70, "quality": 1, "available": True},
        "ORDER_FLOW": {"score": 70, "quality": 1, "available": True},
        "DIRECTION": {"score": 70, "quality": 1, "available": True},
        "MARKET": {"score": 70, "quality": 1, "available": True},
        "_TRUTH": {
            "schema": "DVS_QUANTUM_TRAINING_V1",
            "calibration_state": calibration,
            "drift_state": drift,
            "order_flow_quality": quality,
            "evidence_reliability_state": "VALIDATED",
        },
    })


def seed(path: Path, rows):
    with sqlite3.connect(path) as con:
        con.execute("""CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY, created_at TEXT, lab TEXT, status TEXT,
            result TEXT, confidence REAL, entry_score REAL, risk_score REAL,
            rr_planned REAL, r_multiple REAL, setup_tags TEXT,
            evidence_snapshot_json TEXT)""")
        for i, snap in enumerate(rows, 1):
            con.execute(
                "INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (i, f"2026-01-01 {i%24:02d}:00:00", "SHADOW", "CLOSED",
                 "TP2", 60, 60, 35, 1.8, 1.0, "TREND_EARLY_FORMATION", snap),
            )


def config(path: Path):
    path.write_text(json.dumps({
        "main_confidence": 68, "main_entry": 62,
        "main_risk_max": 50, "main_rr_min": 1.8,
        "shadow_confidence": 45, "shadow_entry": 45,
        "shadow_risk_max": 65, "shadow_rr_min": 1.4,
    }), encoding="utf-8")


def test_quantum_filters_watch_drift_degraded_and_legacy(tmp_path):
    db = tmp_path / "paper.db"
    seed(db, [snapshot(), snapshot(drift="WATCH"), snapshot(drift="DRIFT"),
              snapshot(quality="DEGRADED"), snapshot(calibration="REJECTED_VALIDATION"), ""])
    cfg = tmp_path / "config.json"; config(cfg)
    opt = QuantumOptimizer(str(db), str(cfg), min_closed=40)
    rows = opt._load_closed()
    assert len(rows) == 1
    audit = opt._last_training_audit
    assert audit["excluded_drift"] == 2
    assert audit["excluded_order_flow_quality"] == 1
    assert audit["excluded_calibration"] == 1
    assert audit["excluded_missing_snapshot"] == 1


def test_invalid_snapshot_is_not_inferred(tmp_path):
    db = tmp_path / "paper.db"
    seed(db, [json.dumps({"reasoning": "looks bullish"})])
    cfg = tmp_path / "config.json"; config(cfg)
    opt = QuantumOptimizer(str(db), str(cfg))
    assert opt._load_closed() == []
    assert opt._last_training_audit["excluded_invalid_snapshot"] == 1


def test_insufficient_quality_data_reports_exclusion_audit(tmp_path):
    db = tmp_path / "paper.db"
    seed(db, [snapshot(drift="DRIFT") for _ in range(80)])
    cfg = tmp_path / "config.json"; config(cfg)
    report = QuantumOptimizer(str(db), str(cfg), min_closed=40).optimize()
    assert report["status"] == "INSUFFICIENT_QUALITY_DATA"
    assert report["closed"] == 0
    assert report["total_closed"] == 80
    assert report["training_audit"]["excluded_drift"] == 80


def test_shadow_candidate_does_not_mutate_running_config(tmp_path):
    cfg = tmp_path / "config.json"; config(cfg)
    before = cfg.read_text(encoding="utf-8")
    opt = QuantumOptimizer(str(tmp_path / "none.db"), str(cfg))
    candidate = opt.create_shadow_candidate({
        "safe_to_apply_shadow": True,
        "status": "RECOMMENDATION",
        "training_audit": {"eligible": 100},
        "best_params": {
            "shadow_confidence": 55, "shadow_entry": 55,
            "shadow_risk_max": 75, "shadow_rr_min": 1.8,
        },
    }, str(tmp_path / "candidate.json"))
    assert cfg.read_text(encoding="utf-8") == before
    assert candidate["main_config_mutated"] is False
    assert candidate["human_approval_required"] is True
    assert Path(candidate["path"]).exists()


def test_direct_shadow_apply_is_disabled(tmp_path):
    cfg = tmp_path / "config.json"; config(cfg)
    opt = QuantumOptimizer(str(tmp_path / "none.db"), str(cfg))
    with pytest.raises(RuntimeError):
        opt.apply_shadow_only({"safe_to_apply_shadow": True})
