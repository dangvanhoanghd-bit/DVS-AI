import dataclasses, json, sqlite3
from pathlib import Path
from dvs_ai.services.evidence_analysis import (
    ObservableFilters, ObservableRepository, ObservableUniverseEngine,
    ThresholdProfileLoader, EvidenceAnalysisPipeline, EvidenceReportEngine,
    IntegrityReportEngine, ConfidenceEngine, ConfidenceInput,
    GapPlanner, GapPlanningInput, RecommendationMapper, RecommendationStateInput,
    StageState,
)

ROOT = Path(__file__).parents[1]

def load_profile():
    return ThresholdProfileLoader(
        ROOT/'config/evidence_analysis/observable_thresholds.json',
        ROOT/'config/evidence_analysis/observable_thresholds.manifest.json',
    ).load()

def make_context(tmp_path, n=60, outcome=1.0, same_day=False):
    db=tmp_path/'x.db'
    with sqlite3.connect(db) as c:
        c.execute('''CREATE TABLE shadow_observations(id INTEGER PRIMARY KEY,created_at TEXT,candidate_id TEXT,symbol TEXT,direction TEXT,regime TEXT,baseline_decision TEXT,shadow_decision TEXT,baseline_score REAL,shadow_score REAL,paper_trade_id INTEGER,outcome_r REAL,outcome_result TEXT,closed_at TEXT,truth_json TEXT)''')
        for i in range(1,n+1):
            created='2026-01-01T00:00:00' if same_day else f'2026-01-{1+(i-1)//10:02d}T00:00:00'
            c.execute('INSERT INTO shadow_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(
                i,created,'C1','BTCUSDT','LONG','BULL','READY','READY',70,70,i,outcome,'TP','2026-02-01',json.dumps({'order_flow_quality':'FULL'})))
    profile=load_profile()
    context=ObservableUniverseEngine(ObservableRepository(db),profile).build_context(
        ObservableFilters(regime='BULL',direction='LONG',variant='SHADOW'))
    return context,profile

def test_confidence_rejects_tampered_evidence_artifact(tmp_path):
    context,_=make_context(tmp_path)
    integrity=IntegrityReportEngine.build(context)
    evidence=EvidenceReportEngine.build(context,integrity)
    tampered=dataclasses.replace(evidence, selected_outcomes=(99.0,)*60)
    report=ConfidenceEngine.build(ConfidenceInput(
        context.protocol_version, context.context_id, context.artifact_hash,
        context.observability_state, context.power_state, integrity.state, tampered))
    assert report.state is StageState.ANALYSIS_ABORTED
    assert report.conclusion_state == 'UNOBSERVABLE'

def test_confidence_is_deterministic_and_explained(tmp_path):
    context,_=make_context(tmp_path,n=60,outcome=1.0)
    result1=EvidenceAnalysisPipeline(load_profile()).run(context)
    result2=EvidenceAnalysisPipeline(load_profile()).run(context)
    assert result1.confidence == result2.confidence
    assert result1.confidence.probability_positive == 1.0
    assert result1.confidence.interval_width == 0.0
    assert result1.confidence.engine_version == '1.1'

def test_underpowered_still_blocked_after_framework_split(tmp_path):
    context,profile=make_context(tmp_path,n=30,outcome=10.0)
    result=EvidenceAnalysisPipeline(profile).run(context)
    assert result.confidence.conclusion_state == 'OBSERVABLE_BUT_UNDERPOWERED'
    assert result.recommendation.state is StageState.SKIPPED
    assert result.recommendation.recommendation == 'COLLECT_MORE_DATA'

def test_gap_eta_unknown_when_velocity_is_not_measurable(tmp_path):
    context,profile=make_context(tmp_path,n=30,same_day=True)
    gap=GapPlanner.build(GapPlanningInput(
        context.context_id,context.sample_count,context.paired_sample_count,
        context.observability_state,context.power_state,
        tuple(o.created_at for o in context.observations),False),profile)
    assert gap.gaps[0].missing == 30
    assert gap.gaps[0].eta_days is None
    assert gap.eta_reliable is False

def test_recommendation_mapper_cannot_promote_without_all_hard_gates():
    result=RecommendationMapper.build(RecommendationStateInput(
        StageState.PASS,'OBSERVABLE','UNPOWERED',StageState.PASS,'SUPPORTED'))
    assert result.state is StageState.SKIPPED
    assert result.recommendation == 'COLLECT_MORE_DATA'
    assert result.actionable is False

def test_new_downstream_modules_are_storage_and_statistics_isolated():
    base=ROOT/'dvs_ai/services/evidence_analysis'
    confidence=(base/'confidence_engine.py').read_text(encoding='utf-8').lower()
    gap=(base/'gap_planner.py').read_text(encoding='utf-8').lower()
    mapper=(base/'recommendation_mapper.py').read_text(encoding='utf-8').lower()
    for text in (confidence,gap,mapper):
        assert 'sqlite3' not in text
        assert 'observablerepository' not in text
        assert 'connect(' not in text
    assert 'random' not in mapper
    assert 'bootstrap' not in mapper
    assert 'threshold' not in mapper
    assert 'frozenobservablecontext' not in mapper
