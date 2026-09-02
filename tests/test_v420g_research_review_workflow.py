import json
import sqlite3
from pathlib import Path

import pytest

from dvs_ai.services.research_review_workflow import ResearchReviewWorkflowService, ENGINE_MD5


def seed_workspace(path: Path):
    with sqlite3.connect(path) as c:
        c.executescript('''
        CREATE TABLE research_experiments(
            experiment_id TEXT PRIMARY KEY,name TEXT,hypothesis TEXT,analysis_type TEXT,
            parameters_json TEXT,snapshot_id TEXT,status TEXT,created_at TEXT,started_at TEXT,
            finished_at TEXT,result_json TEXT,result_sha256 TEXT,error TEXT,engine_md5 TEXT
        );
        CREATE TABLE research_comparisons(
            comparison_id TEXT PRIMARY KEY,created_at TEXT,experiment_ids_json TEXT,status TEXT,
            verdict TEXT,report_sha256 TEXT,engine_md5 TEXT
        );
        CREATE TABLE research_cohorts(
            cohort_id TEXT PRIMARY KEY,name TEXT,created_at TEXT,status TEXT,experiment_ids_json TEXT,
            configuration_sha256 TEXT,summary_sha256 TEXT,engine_md5 TEXT
        );
        ''')
        c.execute('INSERT INTO research_experiments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  ('e1','Experiment A','H','DATASET_PROFILE','{}','s1','FINISHED','2026',None,'2026','{}','result-1',None,ENGINE_MD5))
        c.execute('INSERT INTO research_comparisons VALUES(?,?,?,?,?,?,?)',
                  ('x1','2026',json.dumps(['e1']),'FINISHED','REPRODUCIBLE','report-1',ENGINE_MD5))
        c.execute('INSERT INTO research_cohorts VALUES(?,?,?,?,?,?,?,?)',
                  ('c1','Cohort A','2026','FINISHED',json.dumps(['e1']),'cfg-1','summary-1',ENGINE_MD5))


def test_review_lifecycle_and_annotation_are_isolated(tmp_path):
    workspace=tmp_path/'workspace.db'; reviews=tmp_path/'reviews.db'; seed_workspace(workspace)
    before=workspace.read_bytes()
    service=ResearchReviewWorkflowService(str(workspace),str(reviews))
    rid=service.create_review('EXPERIMENT','e1','alice')
    service.add_annotation(rid,'alice','Kiểm tra phương pháp','METHOD')
    assert service.transition(rid,'IN_REVIEW','alice')['state']=='IN_REVIEW'
    assert service.transition(rid,'APPROVED','bob')['state']=='APPROVED'
    result=service.get_review(rid)
    assert result['integrity']['matches'] is True
    assert len(result['annotations'])==1
    assert workspace.read_bytes()==before


def test_invalid_transitions_and_finalized_immutability(tmp_path):
    workspace=tmp_path/'workspace.db'; reviews=tmp_path/'reviews.db'; seed_workspace(workspace)
    service=ResearchReviewWorkflowService(str(workspace),str(reviews))
    rid=service.create_review('COHORT','c1','alice')
    with pytest.raises(ValueError): service.transition(rid,'APPROVED','alice')
    service.transition(rid,'IN_REVIEW','alice')
    with pytest.raises(ValueError): service.transition(rid,'REJECTED','alice','')
    service.transition(rid,'REJECTED','alice','Không đủ bằng chứng')
    with pytest.raises(ValueError): service.add_annotation(rid,'alice','ghi chú muộn')


def test_target_checksum_drift_is_detected(tmp_path):
    workspace=tmp_path/'workspace.db'; reviews=tmp_path/'reviews.db'; seed_workspace(workspace)
    service=ResearchReviewWorkflowService(str(workspace),str(reviews))
    rid=service.create_review('COMPARISON','x1','alice')
    with sqlite3.connect(workspace) as c:
        c.execute("UPDATE research_comparisons SET report_sha256='changed' WHERE comparison_id='x1'")
    assert service.verify_target_integrity(rid)['matches'] is False


def test_export_contains_boundary(tmp_path):
    workspace=tmp_path/'workspace.db'; reviews=tmp_path/'reviews.db'; seed_workspace(workspace)
    service=ResearchReviewWorkflowService(str(workspace),str(reviews))
    rid=service.create_review('EXPERIMENT','e1','alice')
    jp=tmp_path/'review.json'; hp=tmp_path/'review.html'
    service.export_json(rid,str(jp)); service.export_html(rid,str(hp))
    data=json.loads(jp.read_text(encoding='utf-8'))
    assert data['schema']=='research-review-v1'
    assert data['scientific_boundary']['research_result_mutation'] is False
    assert 'no experiment result mutation' in hp.read_text(encoding='utf-8')
