from __future__ import annotations

import json
from pathlib import Path

import pytest

from dvs_ai.services.quantum_burn_in_ledger import BurnInLedgerError, BurnInMilestoneLedger
from dvs_ai.services.quantum_burn_in_program import QuantumBurnInProgram
from dvs_ai.services.quantum_burn_in_quality import BurnInQualityFilter
from dvs_ai.services.quantum_cross_pipeline_monitor import CrossPipelineMonitor
from dvs_ai.services.quantum_data_convergence.adapter import QuantumDataAdapter
from dvs_ai.services.quantum_data_convergence.mapping import map_legacy_outcome
from dvs_ai.services.quantum_data_convergence.models import UnifiedOutcome


def valid_snapshot() -> dict:
    payload = {}
    for family in ("TIMING", "ENTRY", "ORDER_FLOW", "DIRECTION", "MARKET"):
        payload[family] = {"available": True, "score": 0.5, "quality": 1.0}
    payload["_TRUTH"] = {
        "schema": "DVS_QUANTUM_TRAINING_V1",
        "calibration_state": "VALIDATED",
        "drift_state": "STABLE",
        "order_flow_quality": "FULL",
    }
    return payload


def row(source: str, source_id: str, *, outcome: str = "WIN", snapshot=None, provenance=None) -> UnifiedOutcome:
    return UnifiedOutcome(
        source=source,
        source_id=source_id,
        symbol="BTCUSDT",
        direction="LONG",
        setup_time="2026-07-01T00:00:00+00:00",
        close_time="2026-07-01T01:00:00+00:00",
        outcome=outcome,
        realized_r=1.25 if outcome == "WIN" else -1.0,
        confidence=0.8,
        evidence_snapshot=valid_snapshot() if snapshot is None else snapshot,
        original_status="CLOSED",
        original_result=outcome,
        provenance=provenance or {},
    )


class StaticSource:
    def __init__(self, rows):
        self.rows = list(rows)

    def read_terminal(self):
        return list(self.rows)


def test_quality_filter_is_deterministic_and_fail_closed():
    rows = [
        row("paper_trades", "1"),
        row("paper_trades", "2", outcome="AMBIGUOUS"),
        row("paper_trades", "3", snapshot={}),
    ]
    report = BurnInQualityFilter().evaluate(rows)
    assert report.eligible == 1
    assert report.excluded == 2
    assert report.eligible_identities == ("paper_trades:1",)
    assert report.exclusion_reasons["NON_DETERMINATE_OUTCOME"] == 1
    assert report.exclusion_reasons["INVALID_EVIDENCE_SNAPSHOT"] == 1
    assert report.dataset_sha256 == BurnInQualityFilter().evaluate(reversed(rows)).dataset_sha256


def test_quality_filter_rejects_duplicate_identity():
    duplicate = row("paper_trades", "1")
    report = BurnInQualityFilter().evaluate([duplicate, duplicate])
    assert report.eligible == 0
    assert report.exclusion_reasons["DUPLICATE_IDENTITY"] == 2


def test_cross_pipeline_monitor_reports_but_never_deduplicates():
    rows = [
        row("paper_trades", "1", provenance={"decision_id": "D-1"}),
        row("candidate_outcomes", "O-1", provenance={"decision_id": "D-1"}),
    ]
    report = CrossPipelineMonitor().inspect(rows)
    assert report.total == 2
    assert report.action == "REVIEW_REQUIRED"
    assert len(report.exact_link_overlaps) == 1
    assert set(report.exact_link_overlaps[0].identities) == {"paper_trades:1", "candidate_outcomes:O-1"}


def test_soft_overlap_is_review_only():
    rows = [row("paper_trades", "1"), row("candidate_outcomes", "O-1")]
    report = CrossPipelineMonitor().inspect(rows)
    assert not report.exact_link_overlaps
    assert len(report.potential_overlaps) == 1
    assert report.potential_overlaps[0].reason == "SOFT_FINGERPRINT_REVIEW_ONLY"


def test_milestone_ledger_appends_each_threshold_once(tmp_path: Path):
    ledger = BurnInMilestoneLedger(tmp_path / "milestones.jsonl")
    assert ledger.record_reached(eligible_outcomes=29, dataset_sha256="a") == []
    first = ledger.record_reached(eligible_outcomes=100, dataset_sha256="b")
    assert [item["threshold"] for item in first] == [30, 100]
    assert all(item["authority_granted"] is False for item in first)
    assert ledger.record_reached(eligible_outcomes=100, dataset_sha256="b") == []
    second = ledger.record_reached(eligible_outcomes=500, dataset_sha256="c")
    assert [item["threshold"] for item in second] == [300, 500]
    assert ledger.verify()


def test_milestone_ledger_fails_closed_on_tamper(tmp_path: Path):
    path = tmp_path / "milestones.jsonl"
    ledger = BurnInMilestoneLedger(path)
    ledger.record_reached(eligible_outcomes=30, dataset_sha256="a")
    data = json.loads(path.read_text().splitlines()[0])
    data["eligible_outcomes_observed"] = 999
    path.write_text(json.dumps(data) + "\n")
    assert ledger.verify() is False
    with pytest.raises(BurnInLedgerError):
        ledger.record_reached(eligible_outcomes=100, dataset_sha256="b")


def test_program_snapshot_and_dashboard_never_grant_authority(tmp_path: Path):
    rows = [row("paper_trades", str(index)) for index in range(30)]
    adapter = QuantumDataAdapter(StaticSource(rows))
    program = QuantumBurnInProgram(
        tmp_path / "unused.db",
        ledger_path=tmp_path / "ledger.jsonl",
        adapter=adapter,
    )
    result = program.snapshot(persist_milestones=True)
    assert result.quality["eligible"] == 30
    assert result.burn_in["stage"] == "QBP-1_30_OUTCOMES"
    assert result.dashboard["capabilities"]["resolved_outcome_review"] is True
    assert result.dashboard["capabilities"]["walk_forward"] is False
    assert result.authority_granted is False
    assert result.production_or_execution_authority is False
    assert BurnInMilestoneLedger(tmp_path / "ledger.jsonl").verify()


def test_legacy_invalid_semantics_and_partial_stop_exception_are_explicit():
    invalid = map_legacy_outcome(status="CLOSED", result="INVALID", realized_r=-1)
    partial = map_legacy_outcome(status="CLOSED", result="PARTIAL_STOP", realized_r=0.2)
    assert invalid.unified == "LOSS"
    assert invalid.rule_id == "LEGACY_INVALID_TO_LOSS_V1"
    assert partial.unified == "WIN"
    assert partial.rule_id == "LEGACY_PARTIAL_STOP_R_SIGN_V1"

from dvs_ai.services.quantum_burn_in_snapshot_store import BurnInSnapshotStore, BurnInSnapshotStoreError
from dvs_ai.services.quantum_burn_in_qualification import QBP1ReleaseQualifier


def test_snapshot_history_is_hash_chained_and_latest_is_atomic(tmp_path: Path):
    history = tmp_path / "history.jsonl"
    latest = tmp_path / "latest.json"
    rows = [row("paper_trades", "1")]
    program = QuantumBurnInProgram(
        tmp_path / "database.db",
        ledger_path=tmp_path / "milestones.jsonl",
        history_path=history,
        latest_snapshot_path=latest,
        adapter=QuantumDataAdapter(StaticSource(rows)),
    )
    first = program.snapshot(persist_history=True)
    second = program.snapshot(persist_history=True)
    store = BurnInSnapshotStore(history)
    assert store.verify()
    assert [item["sequence"] for item in store.read()] == [1, 2]
    assert json.loads(latest.read_text())["quality"]["eligible"] == second.quality["eligible"] == 1
    assert first.authority_granted is False


def test_snapshot_history_fails_closed_on_tamper(tmp_path: Path):
    path = tmp_path / "history.jsonl"
    store = BurnInSnapshotStore(path)
    store.append({"quality": {"eligible": 0, "dataset_sha256": "x"}, "burn_in": {"stage": "S"}, "cross_pipeline": {"action": "A"}})
    item = json.loads(path.read_text().splitlines()[0])
    item["eligible_outcomes"] = 999
    path.write_text(json.dumps(item) + "\n")
    assert store.verify() is False
    with pytest.raises(BurnInSnapshotStoreError):
        store.append({})


def test_qbp1_qualifier_is_observe_only_and_blocks_invalid_history(tmp_path: Path):
    db = tmp_path / "database.db"
    db.touch()
    ledger = tmp_path / "milestones.jsonl"
    history = tmp_path / "history.jsonl"
    qualifier = QBP1ReleaseQualifier(db, ledger_path=ledger, history_path=history)
    result = qualifier.evaluate()
    assert result.status == "QUALIFIED_OBSERVE_ONLY_COLLECTION"
    assert result.authority_granted is False
    assert result.production_or_execution_authority is False
    history.write_text("{bad json}\n")
    blocked = qualifier.evaluate()
    assert blocked.status == "BLOCKED_NOT_QUALIFIED"
    assert blocked.checks["snapshot_history_valid"] is False
