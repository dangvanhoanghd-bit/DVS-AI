from pathlib import Path

from dvs_ai.services.candidate_lifecycle_store import CandidateLifecycleStore
from dvs_ai.services.historical_candidate_store import HistoricalCandidateStore
from dvs_ai.services.historical_readiness_trend import HistoricalReadinessTrendAudit, HistoricalReadinessTrendStore


def add(store, cid, i, exp, dd=0.2, brier=0.18, coverage=0.75, drift='STABLE'):
    return store.append(cid, observations=(i+1)*20, expectancy=exp, max_drawdown=dd,
        win_rate=0.6, profit_factor=1.4, brier=brier, ece=0.05,
        reliability=0.7, drift_state=drift, coverage=coverage,
        regime_metrics={'BULL':{'count':10}}, snapshot_key=f'{cid}:{i}')


def test_single_good_snapshot_is_insufficient(tmp_path):
    db=tmp_path/'x.db'; store=HistoricalCandidateStore(str(db)); add(store,'C1',0,0.12)
    result=HistoricalReadinessTrendAudit(min_snapshots=4).evaluate('C1',store.snapshots('C1'))
    assert result.state == 'INSUFFICIENT_DATA'


def test_stable_history_becomes_ready(tmp_path):
    db=tmp_path/'x.db'; store=HistoricalCandidateStore(str(db))
    for i,v in enumerate((0.06,0.07,0.08,0.09)): add(store,'C1',i,v,dd=0.2+i*0.01,brier=0.18-i*0.005)
    result=HistoricalReadinessTrendAudit().evaluate('C1',store.snapshots('C1'))
    assert result.state == 'READY_FOR_REVIEW'
    assert result.metrics['positive_snapshot_ratio'] == 1.0


def test_late_drift_or_drawdown_blocks_ready(tmp_path):
    db=tmp_path/'x.db'; store=HistoricalCandidateStore(str(db))
    for i,v in enumerate((0.08,0.09,0.10,0.11)): add(store,'C1',i,v,dd=0.2 if i<3 else 0.5,drift='DRIFT' if i==3 else 'STABLE')
    result=HistoricalReadinessTrendAudit().evaluate('C1',store.snapshots('C1'))
    assert result.state == 'CANDIDATE_UNSTABLE'


def test_readiness_events_are_append_only_and_deduplicated(tmp_path):
    db=tmp_path/'x.db'; perf=HistoricalCandidateStore(str(db)); trend=HistoricalReadinessTrendStore(str(db))
    for i,v in enumerate((0.06,0.07,0.08,0.09)): add(perf,'C1',i,v)
    result=HistoricalReadinessTrendAudit().evaluate('C1',perf.snapshots('C1'))
    first=trend.append_once(result); second=trend.append_once(result)
    assert first is not None and second is None
    assert len(trend.events('C1')) == 1


def test_no_execution_dependency():
    text=Path('dvs_ai/services/historical_readiness_trend.py').read_text(encoding='utf-8').lower()
    assert 'send_order' not in text and 'position_sizer' not in text and 'tradeintent' not in text
