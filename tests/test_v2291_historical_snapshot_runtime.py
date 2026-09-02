from datetime import datetime, timezone

from dvs_ai.services.candidate_lifecycle_store import CandidateLifecycleStore
from dvs_ai.services.historical_candidate_store import HistoricalCandidateStore
from dvs_ai.services.historical_snapshot_runtime import HistoricalSnapshotRuntime
from dvs_ai.services.shadow_observation_service import ShadowObservationStore


def _seed(store, candidate='C1', count=20):
    now=datetime.now(timezone.utc).isoformat()
    for i in range(count):
        oid=store.append(candidate_id=candidate,symbol='BTCUSDT',direction='LONG',regime='BULL' if i%2==0 else 'RANGE',baseline_decision='WAIT',shadow_decision='READY',baseline_score=50,shadow_score=70,truth={'schema':'DVS_SHADOW_OBSERVATION_V1','calibrated_probability':0.6,'drift_state':'STABLE','evidence_reliability':0.7},created_at=now)
        assert store.bind_trade(oid, i+1)
        assert store.close_for_trade(i+1, 1.0 if i%2==0 else -0.5, result='CLOSED', closed_at=now)


def test_snapshot_created_once_per_completed_window(tmp_path):
    db=str(tmp_path/'x.db'); store=ShadowObservationStore(db); _seed(store)
    rt=HistoricalSnapshotRuntime(observation_store=store,window_size=20)
    first=rt.capture('C1'); second=rt.capture('C1')
    assert first.state=='CREATED'
    assert second.state=='DEDUPLICATED'
    assert len(HistoricalCandidateStore(db).snapshots('C1'))==1


def test_incomplete_window_is_blocked(tmp_path):
    db=str(tmp_path/'x.db'); store=ShadowObservationStore(db); _seed(store,count=19)
    result=HistoricalSnapshotRuntime(observation_store=store,window_size=20).capture('C1')
    assert result.state=='BLOCKED'
    assert HistoricalCandidateStore(db).latest('C1') is None


def test_snapshot_transitions_applied_candidate_to_observing(tmp_path):
    db=str(tmp_path/'x.db'); lifecycle=CandidateLifecycleStore(db)
    lifecycle.transition('C1','CREATED',reason='x')
    lifecycle.transition('C1','BACKTESTED',reason='x')
    lifecycle.transition('C1','PENDING_REVIEW',reason='x')
    lifecycle.transition('C1','APPLIED_TO_SHADOW',reason='x')
    store=ShadowObservationStore(db); _seed(store)
    result=HistoricalSnapshotRuntime(observation_store=store,lifecycle_store=lifecycle,window_size=20).capture('C1')
    assert result.state=='CREATED'
    assert lifecycle.current_state('C1')=='OBSERVING'


def test_runtime_has_no_execution_dependency():
    import inspect
    import dvs_ai.services.historical_snapshot_runtime as module
    source=inspect.getsource(module)
    for forbidden in ('TradeIntent','PositionSizer','send_order','execution_live_enabled'):
        assert forbidden not in source
