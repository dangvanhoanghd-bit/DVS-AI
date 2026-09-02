import json
import sqlite3
from pathlib import Path

from dvs_ai.services.research_lineage_provenance import ResearchLineageProvenanceService, ENGINE_MD5


def seed(path: Path):
    with sqlite3.connect(path) as c:
        c.executescript('''
        CREATE TABLE research_snapshots(snapshot_id TEXT PRIMARY KEY,created_at TEXT,source_path TEXT,source_sha256 TEXT,manifest_json TEXT,manifest_sha256 TEXT);
        CREATE TABLE research_experiments(experiment_id TEXT PRIMARY KEY,name TEXT,analysis_type TEXT,snapshot_id TEXT,status TEXT,created_at TEXT,result_sha256 TEXT,engine_md5 TEXT);
        CREATE TABLE research_comparisons(comparison_id TEXT PRIMARY KEY,created_at TEXT,experiment_ids_json TEXT,status TEXT,verdict TEXT,report_sha256 TEXT,engine_md5 TEXT);
        CREATE TABLE research_cohorts(cohort_id TEXT PRIMARY KEY,name TEXT,created_at TEXT,status TEXT,experiment_ids_json TEXT,configuration_sha256 TEXT,summary_sha256 TEXT,engine_md5 TEXT);
        ''')
        c.execute('INSERT INTO research_snapshots VALUES(?,?,?,?,?,?)',('s1','2026','source.db','abc','{}','m1'))
        c.execute('INSERT INTO research_snapshots VALUES(?,?,?,?,?,?)',('s2','2026','source.db','abc','{}','m2'))
        c.execute('INSERT INTO research_experiments VALUES(?,?,?,?,?,?,?,?)',('e1','A','DATASET_PROFILE','s1','FINISHED','2026','r1',ENGINE_MD5))
        c.execute('INSERT INTO research_experiments VALUES(?,?,?,?,?,?,?,?)',('e2','B','DATASET_PROFILE','s1','FINISHED','2026','r1',ENGINE_MD5))
        c.execute('INSERT INTO research_comparisons VALUES(?,?,?,?,?,?,?)',('x1','2026',json.dumps(['e1','e2']),'FINISHED','REPRODUCIBLE','z1',ENGINE_MD5))
        c.execute('INSERT INTO research_cohorts VALUES(?,?,?,?,?,?,?,?)',('c1','C','2026','FINISHED',json.dumps(['e1','e2']),'cfg','sum',ENGINE_MD5))


def test_lineage_detects_branches_duplicates_and_shared_results(tmp_path):
    db=tmp_path/'workspace.db'; seed(db)
    before=db.read_bytes(); report=ResearchLineageProvenanceService(str(db)).analyze()
    assert report['counts']['snapshots']==2
    assert report['counts']['experiments']==2
    assert report['branch_points'][0]['snapshot_id']=='s1'
    assert report['duplicate_source_snapshots']['abc']==['s1','s2']
    assert report['shared_result_groups'][0]['experiment_count']==2
    assert db.read_bytes()==before


def test_lineage_detects_orphans_and_engine_mismatch(tmp_path):
    db=tmp_path/'workspace.db'; seed(db)
    with sqlite3.connect(db) as c:
        c.execute('INSERT INTO research_experiments VALUES(?,?,?,?,?,?,?,?)',('e3','C','DATASET_PROFILE','missing','FINISHED','2026',None,'bad'))
    report=ResearchLineageProvenanceService(str(db)).analyze()
    codes={x['code'] for x in report['issues']}
    assert 'ORPHAN_EXPERIMENT_SNAPSHOT' in codes
    assert 'ENGINE_MD5_MISMATCH' in codes


def test_lineage_exports_json_and_html(tmp_path):
    db=tmp_path/'workspace.db'; seed(db)
    service=ResearchLineageProvenanceService(str(db)); report=service.analyze()
    jp=tmp_path/'lineage.json'; hp=tmp_path/'lineage.html'
    service.export_json(report,str(jp)); service.export_html(report,str(hp))
    assert json.loads(jp.read_text(encoding='utf-8'))['schema']=='research-lineage-v1'
    assert 'no database writes' in hp.read_text(encoding='utf-8')
