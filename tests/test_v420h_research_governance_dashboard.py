import json
import sqlite3
from pathlib import Path

from dvs_ai.services.research_governance_dashboard import ResearchGovernanceDashboardService, ENGINE_MD5
from dvs_ai.services.research_review_workflow import ResearchReviewWorkflowService


def seed_workspace(path: Path):
    with sqlite3.connect(path) as c:
        c.executescript('''
        CREATE TABLE research_experiments(experiment_id TEXT PRIMARY KEY,name TEXT,result_sha256 TEXT);
        CREATE TABLE research_comparisons(comparison_id TEXT PRIMARY KEY,verdict TEXT,report_sha256 TEXT);
        CREATE TABLE research_cohorts(cohort_id TEXT PRIMARY KEY,name TEXT,summary_sha256 TEXT);
        ''')
        c.executemany('INSERT INTO research_experiments VALUES(?,?,?)', [('e1','E1','r1'),('e2','E2','r2')])
        c.execute('INSERT INTO research_comparisons VALUES(?,?,?)', ('x1','REPRODUCIBLE','xsha'))
        c.execute('INSERT INTO research_cohorts VALUES(?,?,?)', ('c1','C1','csha'))


def test_governance_coverage_and_workload(tmp_path):
    workspace=tmp_path/'workspace.db'; reviews=tmp_path/'reviews.db'; seed_workspace(workspace)
    workflow=ResearchReviewWorkflowService(str(workspace),str(reviews))
    rid=workflow.create_review('EXPERIMENT','e1','alice')
    workflow.add_annotation(rid,'alice','note','METHOD')
    workflow.transition(rid,'IN_REVIEW','alice')
    workflow.transition(rid,'APPROVED','bob')
    report=ResearchGovernanceDashboardService(str(workspace),str(reviews)).analyze()
    assert report['summary']['total_targets']==4
    assert report['summary']['reviewed_targets']==1
    assert report['summary']['coverage_rate']==0.25
    assert report['summary']['approved_reviews']==1
    assert report['summary']['checksum_integrity_rate']==1.0
    assert len(report['unreviewed_targets'])==3
    assert report['reviewer_workload'][0]['reviewer']=='alice'
    assert report['reviewer_workload'][0]['annotation_count']==1


def test_checksum_drift_and_orphan_are_detected(tmp_path):
    workspace=tmp_path/'workspace.db'; reviews=tmp_path/'reviews.db'; seed_workspace(workspace)
    workflow=ResearchReviewWorkflowService(str(workspace),str(reviews))
    workflow.create_review('COMPARISON','x1','alice')
    with sqlite3.connect(workspace) as c:
        c.execute("UPDATE research_comparisons SET report_sha256='changed' WHERE comparison_id='x1'")
    with sqlite3.connect(reviews) as c:
        c.execute('INSERT INTO research_reviews VALUES(?,?,?,?,?,?,?,?,?,?)',
                  ('orphan','EXPERIMENT','missing','none','Orphan','DRAFT','2026','2026','bob',ENGINE_MD5))
    report=ResearchGovernanceDashboardService(str(workspace),str(reviews)).analyze()
    assert report['summary']['checksum_failures']==1
    assert report['summary']['orphan_reviews']==1
    assert report['stale_reviews'][0]['target_id']=='x1'


def test_governance_is_read_only_and_exports_boundary(tmp_path):
    workspace=tmp_path/'workspace.db'; reviews=tmp_path/'reviews.db'; seed_workspace(workspace)
    workflow=ResearchReviewWorkflowService(str(workspace),str(reviews)); workflow.create_review('COHORT','c1','alice')
    before_w=workspace.read_bytes(); before_r=reviews.read_bytes()
    service=ResearchGovernanceDashboardService(str(workspace),str(reviews))
    jp=tmp_path/'g.json'; hp=tmp_path/'g.html'; service.export_json(str(jp)); service.export_html(str(hp))
    assert workspace.read_bytes()==before_w and reviews.read_bytes()==before_r
    data=json.loads(jp.read_text(encoding='utf-8'))
    assert data['schema']=='research-governance-v1'
    assert data['scientific_boundary']['decision_engine_invocation'] is False
    assert 'no research result mutation' in hp.read_text(encoding='utf-8')
