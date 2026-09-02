import json, sqlite3
from pathlib import Path
from dvs_ai.services.research_cohort_diagnostics import ResearchCohortDiagnosticsService, ENGINE_MD5


def seed(path: Path):
    c=sqlite3.connect(path)
    c.execute('''CREATE TABLE research_cohorts(cohort_id TEXT PRIMARY KEY,name TEXT,objective TEXT,created_at TEXT,status TEXT,experiment_ids_json TEXT,configuration_sha256 TEXT,started_at TEXT,finished_at TEXT,summary_json TEXT,summary_sha256 TEXT,engine_md5 TEXT)''')
    summaries=[
      {'total_experiments':2,'completed_experiments':2,'completion_rate':1.0,'status_counts':{'FINISHED':2},'analysis_counts':{'DATASET_PROFILE':2},'snapshot_count':1,'snapshot_coverage':{'s1':2},'distinct_result_count':1,'result_groups':{'r1':['e1','e2']}},
      {'total_experiments':2,'completed_experiments':1,'completion_rate':0.5,'status_counts':{'FINISHED':1,'FAILED':1},'analysis_counts':{'STABILITY_CHECK':2},'snapshot_count':2,'snapshot_coverage':{'s1':1,'s2':1},'distinct_result_count':2,'result_groups':{'r1':['e3'],'r2':['e4']}},
    ]
    for i,s in enumerate(summaries,1):
      c.execute('INSERT INTO research_cohorts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(f'c{i}',f'C{i}','o',f'2026-01-0{i}','FINISHED' if i==1 else 'COMPLETED_WITH_EXCEPTIONS','[]','cfg',None,None,json.dumps(s),f'sum{i}',ENGINE_MD5))
    c.commit(); c.close()


def test_cross_study_diagnostics_is_descriptive_and_read_only(tmp_path):
    db=tmp_path/'research.db'; seed(db); before=db.read_bytes()
    r=ResearchCohortDiagnosticsService(str(db)).analyze()
    assert r['cohort_count']==2
    assert r['total_experiments']==4
    assert r['completion_rate_mean']==0.75
    assert r['unique_snapshot_count']==2
    assert r['scientific_boundary']['automatic_tuning'] is False
    assert db.read_bytes()==before


def test_selected_cohorts_and_missing_id(tmp_path):
    db=tmp_path/'research.db'; seed(db); svc=ResearchCohortDiagnosticsService(str(db))
    assert svc.analyze(['c1'])['cohort_count']==1
    try: svc.analyze(['missing'])
    except KeyError: pass
    else: raise AssertionError('missing cohort must fail')


def test_exports_include_boundary(tmp_path):
    db=tmp_path/'research.db'; seed(db); svc=ResearchCohortDiagnosticsService(str(db)); r=svc.analyze()
    jp=tmp_path/'r.json'; hp=tmp_path/'r.html'; svc.export_json(r,str(jp)); svc.export_html(r,str(hp))
    assert 'report_sha256' in json.loads(jp.read_text())
    assert 'no tuning' in hp.read_text().lower()
