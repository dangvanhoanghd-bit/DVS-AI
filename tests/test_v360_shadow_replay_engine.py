from dvs_ai.services.core_shadow_agreement_service import QualificationEvidenceRecord
from dvs_ai.services.qualification_replay_service import QualificationReplayService


def _record(integrity="PASS"):
    return QualificationEvidenceRecord(
        request_id="scan-1", symbol="BTC/USDT:USDT", analysis_revision=7,
        observed_at="2026-07-20T00:00:00+00:00", legacy_action="NO_ACTION",
        unified_action="NO_ACTION", agreement="FULL", confidence=55.0,
        regime="RANGE", phase="B", timeframe="15m", ledger_verified=True,
        synthetic_lifecycle=True, reason_codes=("WAIT",), ledger_hash="abc",
        authorized=False, risk_allowed=False, quantity=0.0,
        event_names=("OBSERVED",), profile_hash="profile", evidence_hash="hash",
        integrity_status=integrity,
    )


def test_replay_is_read_only_and_deterministic():
    session = QualificationReplayService().build(_record())
    assert session.valid is True
    assert session.steps[0].key == "integrity"
    assert session.steps[-1].status == "VERIFIED"
    assert any("Paper Authority remains LEGACY" in step.detail for step in session.steps)
    assert all(not hasattr(QualificationReplayService, name) for name in ("authorize", "execute", "open_position"))


def test_failed_integrity_invalidates_replay():
    session = QualificationReplayService().build(_record("FAILED"))
    assert session.valid is False
    assert session.steps[0].status == "FAILED"
    assert session.steps[-1].status == "INVALID"
