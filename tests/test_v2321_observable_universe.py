import dataclasses, json, sqlite3
from pathlib import Path
import pytest
from dvs_ai.services.evidence_analysis import ObservableFilters, ObservableRepository, ObservableUniverseEngine, ThresholdProfileLoader, ObservableState
from dvs_ai.services.evidence_analysis.observable_thresholds import ThresholdProfileError
from dvs_ai.services.evidence_analysis.protocol_gate import recommendation_gate


def setup_db(path):
    with sqlite3.connect(path) as c:
        c.execute('''CREATE TABLE shadow_observations(id INTEGER PRIMARY KEY,created_at TEXT,candidate_id TEXT,symbol TEXT,direction TEXT,regime TEXT,baseline_decision TEXT,shadow_decision TEXT,baseline_score REAL,shadow_score REAL,paper_trade_id INTEGER,outcome_r REAL,outcome_result TEXT,closed_at TEXT,truth_json TEXT)''')

def add(path, i, regime, direction, candidate='C1', quality='FULL'):
    with sqlite3.connect(path) as c:
        c.execute('INSERT INTO shadow_observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(i,'2026-01-01',candidate,'BTCUSDT',direction,regime,'READY','READY',70,70,i,1.0,'TP','2026-01-02',json.dumps({'order_flow_quality':quality})))

def profile(root): return ThresholdProfileLoader(root/'config/evidence_analysis/observable_thresholds.json',root/'config/evidence_analysis/observable_thresholds.manifest.json').load()

def test_intersection_not_marginal(tmp_path):
    db=tmp_path/'x.db'; setup_db(db)
    for i in range(1,31): add(db,i,'BULL','LONG')
    for i in range(31,61): add(db,i,'BEAR','SHORT')
    root=Path(__file__).parents[1]
    ctx=ObservableUniverseEngine(ObservableRepository(db),profile(root)).build_context(ObservableFilters(regime='BEAR',direction='LONG',variant='SHADOW'))
    assert ctx.sample_count == 0
    assert ctx.observability_state is ObservableState.UNOBSERVABLE
    assert recommendation_gate(ctx).allowed is False

def test_underpowered_is_hard_blocked(tmp_path):
    db=tmp_path/'x.db'; setup_db(db)
    for i in range(1,31): add(db,i,'BULL','LONG')
    root=Path(__file__).parents[1]
    ctx=ObservableUniverseEngine(ObservableRepository(db),profile(root)).build_context(ObservableFilters(regime='BULL',direction='LONG',variant='SHADOW'))
    assert ctx.observability_state is ObservableState.OBSERVABLE_BUT_UNDERPOWERED
    assert recommendation_gate(ctx).state == 'SKIPPED'

def test_powered_context_allowed(tmp_path):
    db=tmp_path/'x.db'; setup_db(db)
    for i in range(1,61): add(db,i,'BULL','LONG')
    root=Path(__file__).parents[1]
    ctx=ObservableUniverseEngine(ObservableRepository(db),profile(root)).build_context(ObservableFilters(regime='BULL',direction='LONG',variant='SHADOW'))
    assert recommendation_gate(ctx).allowed is True
    with pytest.raises(dataclasses.FrozenInstanceError): ctx.sample_count=9

def test_fake_context_hash_aborts(tmp_path):
    db=tmp_path/'x.db'; setup_db(db)
    for i in range(1,61): add(db,i,'BULL','LONG')
    root=Path(__file__).parents[1]; engine=ObservableUniverseEngine(ObservableRepository(db),profile(root))
    ctx=engine.build_context(ObservableFilters(regime='BULL',direction='LONG',variant='SHADOW'))
    fake=dataclasses.replace(ctx,artifact_hash='0'*64)
    assert recommendation_gate(fake).state == 'ANALYSIS_ABORTED'

def test_tampered_threshold_profile_fails(tmp_path):
    root=Path(__file__).parents[1]; p=tmp_path/'p.json'; m=tmp_path/'m.json'
    p.write_bytes((root/'config/evidence_analysis/observable_thresholds.json').read_bytes()); m.write_bytes((root/'config/evidence_analysis/observable_thresholds.manifest.json').read_bytes())
    payload=json.loads(p.read_text()); payload['thresholds']['regime_observable']=1; p.write_text(json.dumps(payload))
    with pytest.raises(ThresholdProfileError): ThresholdProfileLoader(p,m).load()

def test_downstream_has_no_sqlite_or_repository_import():
    root=Path(__file__).parents[1]/'dvs_ai/services/evidence_analysis'
    for name in ('protocol_gate.py',):
        text=(root/name).read_text(encoding='utf-8').lower()
        assert 'sqlite3' not in text
        assert 'observablerepository' not in text
        assert '.observable_repository' not in text
