import pytest

from dvs_ai.services.candidate_lifecycle_store import CandidateLifecycleStore
from dvs_ai.services.historical_candidate_store import HistoricalCandidateStore
from dvs_ai.services.candidate_evidence_service import CandidateEvidenceRepository


def test_lifecycle_is_append_only_and_rejects_illegal_reverse(tmp_path):
    db=tmp_path/'history.db'; store=CandidateLifecycleStore(str(db))
    store.transition('C1','CREATED',reason='quantum candidate')
    store.transition('C1','BACKTESTED',reason='holdout pass')
    store.transition('C1','PENDING_REVIEW',reason='human review queued')
    assert [x.new_state for x in store.events('C1')] == ['CREATED','BACKTESTED','PENDING_REVIEW']
    with pytest.raises(ValueError):
        store.transition('C1','CREATED',reason='illegal rewind')
    assert len(store.events('C1')) == 3


def test_performance_snapshots_append_and_preserve_history(tmp_path):
    store=HistoricalCandidateStore(str(tmp_path/'history.db'))
    first=store.append('C1',observations=50,expectancy=.10,max_drawdown=.30,win_rate=.55,
        profit_factor=1.2,brier=.22,ece=.08,reliability=.61,drift_state='STABLE',coverage=.50)
    second=store.append('C1',observations=100,expectancy=.16,max_drawdown=.27,win_rate=.58,
        profit_factor=1.35,brier=.19,ece=.06,reliability=.70,drift_state='STABLE',coverage=.75)
    rows=store.snapshots('C1')
    assert [x.snapshot_id for x in rows] == [first,second]
    assert rows[0].expectancy == .10 and rows[1].expectancy == .16
    assert store.latest('C1').observations == 100


def test_archive_keeps_lifecycle_and_performance(tmp_path):
    db=tmp_path/'data'/'dvs_paper_trades.db'
    lifecycle=CandidateLifecycleStore(str(db)); perf=HistoricalCandidateStore(str(db))
    lifecycle.transition('C1','CREATED',reason='created')
    lifecycle.transition('C1','REJECTED',reason='underperformed')
    lifecycle.transition('C1','ARCHIVED',reason='retain for audit')
    perf.append('C1',observations=80,expectancy=-.04,max_drawdown=.4,win_rate=.44,
        profit_factor=.8,brier=.28,ece=.13,reliability=.48,drift_state='WATCH',coverage=.65)
    assert lifecycle.current_state('C1') == 'ARCHIVED'
    assert len(lifecycle.events('C1')) == 3
    assert perf.latest('C1').expectancy == -.04


def test_repository_exposes_historical_comparison(tmp_path):
    data=tmp_path/'data'; data.mkdir()
    repo=CandidateEvidenceRepository(str(data),str(data/'shadow_promotions'))
    repo.lifecycle.transition('A','CREATED',reason='created')
    repo.lifecycle.transition('B','CREATED',reason='created')
    repo.performance.append('A',observations=100,expectancy=.12,max_drawdown=.2,win_rate=.56,
        profit_factor=1.3,brier=.2,ece=.06,reliability=.7,drift_state='STABLE',coverage=.8)
    repo.performance.append('B',observations=100,expectancy=.05,max_drawdown=.3,win_rate=.51,
        profit_factor=1.05,brier=.23,ece=.09,reliability=.6,drift_state='WATCH',coverage=.6)
    rows={x['candidate_id']:x for x in repo.historical_candidates()}
    assert rows['A']['expectancy'] > rows['B']['expectancy']
    assert len(repo.candidate_trend('A')) == 1
