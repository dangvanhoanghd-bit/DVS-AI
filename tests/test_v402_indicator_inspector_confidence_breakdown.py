from dvs_ai.services.core_shadow_agreement_service import QualificationEvidenceRecord
from dvs_ai.services.qualification_replay_service import QualificationReplayService


def _record():
    return QualificationEvidenceRecord(
        request_id="scan-inspector-1", symbol="BTC/USDT:USDT", analysis_revision=10,
        observed_at="2026-07-20T00:00:00+00:00", legacy_action="NO_ACTION",
        unified_action="NO_ACTION", agreement="FULL", confidence=72.0,
        regime="RANGE", phase="B", timeframe="15m", ledger_verified=True,
        synthetic_lifecycle=True, reason_codes=("CMF_WAIT", "RSI_NEUTRAL", "OI_FLAT"), ledger_hash="abc",
        authorized=False, risk_allowed=False, quantity=0.0,
        event_names=("SPRING_OBSERVED",), profile_hash="profile", evidence_hash="hash",
        integrity_status="PASS",
    )


def test_indicator_inspector_metadata_is_deterministic():
    session = QualificationReplayService().build(_record())
    nodes = {node.label: node for node in session.graph_nodes}
    assert nodes["CMF_WAIT"].category == "CMF"
    assert nodes["CMF_WAIT"].source == "REASON_CODE"
    assert "Chaikin" in nodes["CMF_WAIT"].interpretation
    assert nodes["SPRING_OBSERVED"].source == "SCIENTIFIC_EVENT"
    assert sum(node.contribution for node in session.graph_nodes) == 72.0


def test_inspector_remains_read_only_and_does_not_invent_values():
    session = QualificationReplayService().build(_record())
    rsi = next(node for node in session.graph_nodes if node.label == "RSI_NEUTRAL")
    assert "không nội suy" in rsi.interpretation
    assert all(not hasattr(QualificationReplayService, name) for name in ("authorize", "execute", "promote", "activate"))
