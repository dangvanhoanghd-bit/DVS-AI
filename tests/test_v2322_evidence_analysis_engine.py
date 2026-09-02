import dataclasses, json, sqlite3
from pathlib import Path
from dvs_ai.services.evidence_analysis import (
    ObservableFilters, ObservableRepository, ObservableUniverseEngine,
    ThresholdProfileLoader, EvidenceAnalysisPipeline,
    IntegrityReportEngine, EvidenceReportEngine, ConfidenceReportEngine,
    ActionableGapReportEngine, RecommendationEngine, RecommendationInput,
    StageState,
)


def setup_db(path):
    with sqlite3.connect(path) as c:
        c.execute('''CREATE TABLE shadow_observations(id INTEGER PRIMARY KEY,created_at TEXT,candidate_id TEXT,symbol TEXT,direction TEXT,regime TEXT,baseline_decision TEXT,shadow_decision TEXT,baseline_score REAL,shadow_score REAL,paper_trade_id INTEGER,outcome_r REAL,outcome_result TEXT,closed_at TEXT,truth_json TEXT)''')


def add(path, i, outcome=1.0, created=None, regime='BULL', direction='LONG'):
    created=created or f'2026-01-{1+(i-1)//10:02d}T00:00:00'
    with sqlite3.connect(path) as c:
        c.execute('INSERT INTO shadow_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(
            i,created,'C1','BTCUSDT',direction,regime,'READY','READY',70,70,i,outcome,'TP','2026-02-01',json.dumps({'order_flow_quality':'FULL'})))


def profile(root):
    return ThresholdProfileLoader(root/'config/evidence_analysis/observable_thresholds.json',root/'config/evidence_analysis/observable_thresholds.manifest.json').load()


def context(tmp_path, n=60, outcome=1.0):
    db=tmp_path/'x.db'; setup_db(db)
    for i in range(1,n+1): add(db,i,outcome)
    root=Path(__file__).parents[1]
    p=profile(root)
    ctx=ObservableUniverseEngine(ObservableRepository(db),p).build_context(ObservableFilters(regime='BULL',direction='LONG',variant='SHADOW'))
    return ctx,p


def test_integrity_failure_stops_all_downstream(tmp_path):
    ctx,p=context(tmp_path)
    fake=dataclasses.replace(ctx,artifact_hash='f'*64)
    result=EvidenceAnalysisPipeline(p).run(fake)
    assert result.integrity.state is StageState.FAIL
    assert result.evidence.state is StageState.SKIPPED
    assert result.confidence.state is StageState.SKIPPED
    assert result.recommendation.state is StageState.SKIPPED
    assert result.recommendation.recommendation == 'ANALYSIS_ABORTED'


def test_underpowered_never_generates_recommendation(tmp_path):
    ctx,p=context(tmp_path,n=30,outcome=5.0)
    result=EvidenceAnalysisPipeline(p).run(ctx)
    assert result.evidence.expectancy == 5.0
    assert result.confidence.conclusion_state == 'OBSERVABLE_BUT_UNDERPOWERED'
    assert result.recommendation.state is StageState.SKIPPED
    assert result.recommendation.recommendation == 'COLLECT_MORE_DATA'
    assert result.gap.gaps[0].missing == 30


def test_powered_supported_context_reaches_manual_review_only(tmp_path):
    ctx,p=context(tmp_path,n=60,outcome=1.0)
    result=EvidenceAnalysisPipeline(p).run(ctx)
    assert result.integrity.state is StageState.PASS
    assert result.confidence.conclusion_state == 'SUPPORTED'
    assert result.recommendation.recommendation == 'READY_FOR_MANUAL_REVIEW'
    assert result.recommendation.actionable is True


def test_no_outcomes_is_not_misreported_as_supported(tmp_path):
    ctx,p=context(tmp_path,n=60,outcome=None)
    result=EvidenceAnalysisPipeline(p).run(ctx)
    assert result.confidence.conclusion_state == 'NO_ACTIONABLE_ISSUE_DETECTED'
    assert result.recommendation.recommendation == 'CONTINUE_PAPER'


def test_gap_eta_is_actionable_when_velocity_exists(tmp_path):
    ctx,p=context(tmp_path,n=30,outcome=1.0)
    gap=ActionableGapReportEngine.build(ctx,p)
    assert gap.gaps[0].missing == 30
    assert gap.gaps[0].eta_days is not None
    assert gap.gaps[0].eta_days > 0


def test_downstream_modules_have_no_database_access():
    root=Path(__file__).parents[1]/'dvs_ai/services/evidence_analysis'
    for name in ('integrity_report.py','evidence_report.py','confidence_report.py','actionable_gap_report.py','recommendation_engine.py','analysis_pipeline.py'):
        text=(root/name).read_text(encoding='utf-8').lower()
        assert 'sqlite3' not in text
        assert 'observablerepository' not in text
        assert '.observable_repository' not in text
        assert 'connect(' not in text
