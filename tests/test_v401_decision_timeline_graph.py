from dvs_ai.services.core_shadow_agreement_service import QualificationEvidenceRecord
from dvs_ai.services.qualification_replay_service import QualificationReplayService


def _record():
    return QualificationEvidenceRecord(
        request_id="scan-graph-1", symbol="BTC/USDT:USDT", analysis_revision=9,
        observed_at="2026-07-20T00:00:00+00:00", legacy_action="NO_ACTION",
        unified_action="NO_ACTION", agreement="FULL", confidence=60.0,
        regime="RANGE", phase="B", timeframe="15m", ledger_verified=True,
        synthetic_lifecycle=True, reason_codes=("CMF_WAIT", "RSI_NEUTRAL"), ledger_hash="abc",
        authorized=False, risk_allowed=False, quantity=0.0,
        event_names=("SPRING_OBSERVED",), profile_hash="profile", evidence_hash="hash",
        integrity_status="PASS",
    )


def test_decision_graph_is_deterministic_and_read_only():
    first = QualificationReplayService().build(_record())
    second = QualificationReplayService().build(_record())
    assert first.graph_nodes == second.graph_nodes
    assert first.graph_nodes[0].key == "evidence"
    assert first.graph_nodes[-1].status == "LEGACY"
    assert any(node.label == "CMF_WAIT" for node in first.graph_nodes)
    assert sum(node.contribution for node in first.graph_nodes) == 60.0


def test_graph_does_not_create_execution_authority():
    session = QualificationReplayService().build(_record())
    assert any("quantity 0" in node.detail for node in session.graph_nodes)
    assert all(not hasattr(QualificationReplayService, name) for name in ("authorize", "execute", "promote"))
