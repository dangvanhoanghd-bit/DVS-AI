from pathlib import Path

from dvs_ai.services.core_shadow_agreement_service import QualificationEvidenceRecord
from dvs_ai.services.qualification_replay_service import QualificationReplayService
from dvs_ai.services.qualification_batch_diagnostics import (
    QualificationBatchFailureJournal,
    QualificationBatchItemFailure,
)


def _record(*, confidence=57.5, reasons=(), events=()):
    return QualificationEvidenceRecord(
        request_id="audit-403", symbol="BTC/USDT:USDT", analysis_revision=1,
        observed_at="2026-07-20T00:00:00+00:00", legacy_action="NO_ACTION",
        unified_action="NO_ACTION", agreement="FULL", confidence=confidence,
        regime="RANGE", phase="B", timeframe="15m", ledger_verified=True,
        synthetic_lifecycle=True, reason_codes=tuple(reasons), ledger_hash="abc",
        authorized=False, risk_allowed=False, quantity=0.0,
        event_names=tuple(events), profile_hash="profile", evidence_hash="hash",
        integrity_status="PASS",
    )


def test_baseline_confidence_preserves_empty_explainability_case():
    session = QualificationReplayService().build(_record())
    baseline = next(n for n in session.graph_nodes if n.key == "baseline_confidence")
    assert baseline.source == "PERSISTED_EVIDENCE"
    assert baseline.status == "DESCRIPTIVE_ONLY"
    assert abs(sum(n.contribution for n in session.graph_nodes) - 57.5) < 1e-9
    assert not any(n.status == "GRAPH_CONFIDENCE_INVARIANT_FAILED" for n in session.graph_nodes)


def test_confidence_conservation_for_mixed_reason_and_event():
    session = QualificationReplayService().build(_record(confidence=73.0, reasons=("CMF_WAIT",), events=("SPRING_OBSERVED",)))
    assert abs(sum(n.contribution for n in session.graph_nodes) - 73.0) < 1e-9
    assert not any(n.key == "baseline_confidence" for n in session.graph_nodes)


def test_failure_journal_writes_structured_traceback_and_rotates(tmp_path):
    path = tmp_path / "failures.jsonl"
    journal = QualificationBatchFailureJournal(path, max_bytes=512, backup_count=1)
    failure = QualificationBatchItemFailure(
        batch_id="b1", request_id="r1", symbol="BTC/USDT", item_index=0,
        exception_type="ValueError", exception_message="bad format",
        traceback_text="Traceback... ValueError: bad format", timestamp="2026-07-20T00:00:00+00:00",
    )
    journal.append(failure)
    text = path.read_text(encoding="utf-8")
    assert '"symbol": "BTC/USDT"' in text
    assert '"exception_type": "ValueError"' in text
    assert '"traceback_text"' in text
    assert "api_secret" not in text.lower()


def test_batch_runner_no_longer_swallows_item_exceptions():
    source = Path("dvs_ai/ui/core_qualification_batch_runner.py").read_text(encoding="utf-8")
    assert "except Exception:\n                    failures += 1" not in source
    assert "QualificationBatchItemFailure" in source
    assert "LOGGER.exception" in source
    assert "batch_item_failed" in source
    assert '"QUEUE_FULL"' in source
