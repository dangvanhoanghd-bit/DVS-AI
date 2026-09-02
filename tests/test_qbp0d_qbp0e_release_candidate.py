from __future__ import annotations

import json
import sqlite3

from dvs_ai.services.quantum_burn_in import QuantumBurnInPolicy, QuantumBurnInService
from dvs_ai.services.quantum_data_convergence import DataEquivalenceVerifier
from dvs_ai.services.quantum_validation import (
    AttemptLedger, HoldoutManager, ValidationOrchestrator, ValidationRequest, WalkForwardFold,
)


def _snapshot():
    return json.dumps({
        "TIMING": {"available": True, "score": 60, "quality": 1.0},
        "ENTRY": {"available": True, "score": 60, "quality": 1.0},
        "ORDER_FLOW": {"available": True, "score": 60, "quality": 1.0},
        "DIRECTION": {"available": True, "score": 60, "quality": 1.0},
        "MARKET": {"available": True, "score": 60, "quality": 1.0},
        "_TRUTH": {"schema": "DVS_QUANTUM_TRAINING_V1", "calibration_state": "VALIDATED",
                   "drift_state": "STABLE", "order_flow_quality": "FULL"},
    })


def _db(path, count=4):
    with sqlite3.connect(path) as con:
        con.execute("""CREATE TABLE paper_trades(
          id INTEGER PRIMARY KEY,pilot_id TEXT,lab TEXT,created_at TEXT,closed_at TEXT,
          symbol TEXT,direction TEXT,status TEXT,result TEXT,r_multiple REAL,
          confidence REAL,entry_score REAL,risk_score REAL,rr_planned REAL,
          regime TEXT,evidence_snapshot_json TEXT,setup_tags TEXT)""")
        for i in range(count):
            con.execute("INSERT INTO paper_trades VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                i+1, f"p{i}", "SHADOW", f"2026-01-{i+1:02d}", f"2026-01-{i+2:02d}",
                "BTCUSDT", "LONG" if i % 2 == 0 else "SHORT", "CLOSED",
                "WIN" if i % 2 == 0 else "LOSS", 1.0 if i % 2 == 0 else -1.0,
                70, 65, 20, 2.0, "TREND", _snapshot(), "",
            ))


def test_qbp0d_data_equivalence_compares_full_canonical_payload(tmp_path):
    path = tmp_path / "data.db"; _db(path)
    report = DataEquivalenceVerifier(path).verify()
    assert report.equivalent
    assert report.legacy_count == report.adapter_count == 4
    assert report.legacy_digest == report.adapter_digest
    assert report.legacy_statistics == report.adapter_statistics
    assert report.differences == ()


def test_qbp0e_thresholds_unlock_research_only_and_never_authority():
    expected = [
        (29, "QBP-0E_COLLECTING", False, False),
        (30, "QBP-1_30_OUTCOMES", True, False),
        (100, "QBP-2_100_OUTCOMES", True, False),
        (300, "QBP-3_300_OUTCOMES", True, False),
        (500, "QBP-4_500_PLUS", True, True),
    ]
    for count, stage, review, handover in expected:
        snap = QuantumBurnInPolicy.evaluate(count)
        assert snap.stage == stage
        assert snap.capability_enabled("resolved_outcome_review") is review
        assert snap.paper_authority_handover_eligible is handover
        assert snap.authority_granted is False


def test_qbp0e_service_counts_only_quality_eligible_outcomes(tmp_path):
    path = tmp_path / "data.db"; _db(path, count=31)
    snap = QuantumBurnInService(path).snapshot()
    assert snap.eligible_outcomes == 31
    assert snap.stage == "QBP-1_30_OUTCOMES"
    assert not snap.capability_enabled("walk_forward")


def test_validation_capability_gate_blocks_before_threshold(tmp_path):
    holdout_path = tmp_path / "holdout.jsonl"
    attempts_path = tmp_path / "attempts.jsonl"
    holdout = HoldoutManager(holdout_path)
    holdout.lock("h1", "2026-01-01", "scope")
    orchestrator = ValidationOrchestrator(holdout, AttemptLedger(attempts_path))
    fold = WalkForwardFold("f1", "2025-01-01", "2025-06-01", "2025-06-02", "2025-07-01",
                           "2025-07-02", "2025-08-01", 1, 1)
    req = ValidationRequest(
        study_id="s", policy_scope_id="scope", policy_scope_hash="hash",
        decision_engine_checksum="frozen", replay_state="VERIFIED", effective_n=120,
        minimum_effective_n=100, split_method="PURGED_WALK_FORWARD", folds=(fold,),
        holdout_id="h1", burn_in_eligible_outcomes=99,
        burn_in_required_capabilities=("walk_forward", "purge_embargo"),
    )
    result = orchestrator.validate(req)
    assert result.state.value == "BLOCK"
    assert "BURN_IN_CAPABILITY_LOCKED:walk_forward" in result.violations
    assert "BURN_IN_CAPABILITY_LOCKED:purge_embargo" in result.violations
