from __future__ import annotations

import sqlite3
from pathlib import Path

from dvs_ai.services.candidate_lifecycle_store import CandidateLifecycleStore
from dvs_ai.services.historical_candidate_store import HistoricalCandidateStore
from dvs_ai.services.historical_evidence_repository import HistoricalEvidenceRepository
from dvs_ai.services.historical_readiness_trend import (
    HistoricalReadinessResult,
    HistoricalReadinessTrendStore,
)


def _seed(db: Path, cid: str, expectancy: float, *, archived: bool = False) -> None:
    life = CandidateLifecycleStore(str(db))
    life.transition(cid, "CREATED", reason="seed")
    life.transition(cid, "BACKTESTED", reason="seed")
    life.transition(cid, "PENDING_REVIEW", reason="seed")
    life.transition(cid, "APPLIED_TO_SHADOW", reason="seed")
    life.transition(cid, "OBSERVING", reason="seed")
    perf = HistoricalCandidateStore(str(db))
    for i in range(1, 5):
        sid = perf.append(
            cid,
            observations=i * 20,
            expectancy=expectancy,
            max_drawdown=0.10,
            win_rate=0.58,
            profit_factor=1.3,
            brier=0.20,
            ece=0.05,
            reliability=0.70,
            drift_state="STABLE",
            coverage=0.75,
            captured_at=f"2026-07-{10+i:02d}T00:00:00+00:00",
        )
        HistoricalReadinessTrendStore(str(db)).append_once(
            HistoricalReadinessResult(
                "READY_FOR_REVIEW" if i == 4 else "CONTINUE_OBSERVATION",
                cid,
                i,
                ("seed",),
                {"mean_expectancy": expectancy},
                sid,
            )
        )
    if archived:
        life.transition(cid, "READY_FOR_REVIEW", reason="seed")
        life.transition(cid, "ARCHIVED", reason="seed")


def test_unified_dossier_and_archive_preserve_history(tmp_path: Path) -> None:
    db = tmp_path / "history.db"
    _seed(db, "CAND_A", 0.08, archived=True)
    repo = HistoricalEvidenceRepository(str(db), str(tmp_path / "promotions"))
    dossier = repo.dossier("CAND_A")
    assert dossier["state"] == "ARCHIVED"
    assert dossier["snapshot_count"] == 4
    assert dossier["readiness_count"] == 4
    assert dossier["event_count"] >= 7
    assert dossier["snapshots"][-1]["expectancy"] == 0.08


def test_comparison_ranks_better_candidate_without_deleting_archived(tmp_path: Path) -> None:
    db = tmp_path / "history.db"
    _seed(db, "CAND_WEAK", 0.03, archived=True)
    _seed(db, "CAND_STRONG", 0.11)
    repo = HistoricalEvidenceRepository(str(db))
    rows = repo.comparison()
    assert rows[0]["candidate_id"] == "CAND_STRONG"
    assert {row["candidate_id"] for row in rows} == {"CAND_STRONG", "CAND_WEAK"}
    assert next(row for row in rows if row["candidate_id"] == "CAND_WEAK")["archived"] is True


def test_integrity_audit_detects_orphan_readiness_event(tmp_path: Path) -> None:
    db = tmp_path / "history.db"
    _seed(db, "CAND_A", 0.08)
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "INSERT INTO candidate_readiness_trend_events(candidate_id,snapshot_id,state,reasons_json,metrics_json) VALUES (?,?,?,?,?)",
            ("CAND_A", 999999, "READY_FOR_REVIEW", "[]", "{}"),
        )
    report = HistoricalEvidenceRepository(str(db)).audit_integrity()
    assert report.state == "FAIL"
    assert any("missing snapshot" in issue for issue in report.issues)


def test_dashboard_v2_is_observe_only_and_shows_integrity_comparison() -> None:
    source = Path("dvs_ai/ui/truth_dashboard.py").read_text(encoding="utf-8")
    repository = Path("dvs_ai/services/historical_evidence_repository.py").read_text(encoding="utf-8")
    assert "Historical Evidence Integrity" in source
    assert "history_comparison_table" in source
    assert "candidate_lifecycle_detail" in source
    assert "audit_integrity" in repository
    forbidden = ("send_order", "PositionSizer", "TradeIntent", "apply_shadow", "promote_to_main")
    assert not any(token in repository for token in forbidden)
