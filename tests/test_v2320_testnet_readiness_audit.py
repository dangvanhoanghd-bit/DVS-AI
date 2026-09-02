from types import SimpleNamespace
from dvs_ai.services.testnet_readiness_service import TestnetReadinessAuditService


def op(health='HEALTHY', score=90, coverage='FULL', eligible=100, regimes='SUPPORTED', alerts=()):
    return SimpleNamespace(
        health=SimpleNamespace(state=health, score=score, alerts=alerts),
        coverage=SimpleNamespace(state=coverage, eligible=eligible),
        regimes=SimpleNamespace(state=regimes),
    )


def test_ready_requires_all_dimensions(tmp_path):
    svc=TestnetReadinessAuditService(str(tmp_path/'x.db'))
    snap=svc.evaluate(operational=op(), historical_integrity={'state':'PASS'}, candidate_state='OBSERVING', candidate_readiness='READY_FOR_REVIEW')
    assert snap.state == 'READY_FOR_MANUAL_TESTNET_REVIEW'
    assert not snap.testnet_enabled and not snap.live_enabled


def test_blocked_data_is_insufficient(tmp_path):
    svc=TestnetReadinessAuditService(str(tmp_path/'x.db'))
    snap=svc.evaluate(operational=op(coverage='BLOCKED', eligible=0, regimes='INSUFFICIENT_DATA'), historical_integrity={'state':'PASS'})
    assert snap.state == 'DATA_INSUFFICIENT'


def test_critical_health_is_operational_risk(tmp_path):
    svc=TestnetReadinessAuditService(str(tmp_path/'x.db'))
    snap=svc.evaluate(operational=op(health='CRITICAL', score=20), historical_integrity={'state':'PASS'}, candidate_readiness='READY_FOR_REVIEW')
    assert snap.state == 'OPERATIONAL_RISK'


def test_safety_violation_is_not_ready(tmp_path):
    svc=TestnetReadinessAuditService(str(tmp_path/'x.db'))
    snap=svc.evaluate(operational=op(), historical_integrity={'state':'PASS'}, candidate_readiness='READY_FOR_REVIEW', live_enabled=True)
    assert snap.state == 'NOT_READY'


def test_history_append_is_deduplicated(tmp_path):
    svc=TestnetReadinessAuditService(str(tmp_path/'x.db'))
    snap=svc.evaluate(operational=op(), historical_integrity={'state':'PASS'}, candidate_readiness='READY_FOR_REVIEW')
    assert svc.append(snap, 'same') is True
    assert svc.append(snap, 'same') is False
    assert len(svc.recent()) == 1
