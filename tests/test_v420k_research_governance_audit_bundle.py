from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

from dvs_ai.services.research_governance_audit_bundle import ENGINE_MD5, ResearchGovernanceAuditBundleService


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixtures(tmp_path: Path):
    workspace = tmp_path / 'research_workspace.db'
    reviews = tmp_path / 'research_reviews.db'
    ledger = tmp_path / 'research_governance_ledger.db'
    with sqlite3.connect(workspace) as c:
        c.executescript('''
        CREATE TABLE research_snapshots(snapshot_id TEXT,created_at TEXT,source_path TEXT,source_sha256 TEXT,manifest_sha256 TEXT);
        CREATE TABLE research_experiments(experiment_id TEXT,name TEXT,analysis_type TEXT,snapshot_id TEXT,status TEXT,created_at TEXT,result_sha256 TEXT,engine_md5 TEXT);
        CREATE TABLE research_comparisons(comparison_id TEXT,created_at TEXT,experiment_ids_json TEXT,status TEXT,verdict TEXT,report_sha256 TEXT,engine_md5 TEXT);
        CREATE TABLE research_cohorts(cohort_id TEXT,name TEXT,created_at TEXT,status TEXT,experiment_ids_json TEXT,configuration_sha256 TEXT,summary_sha256 TEXT,engine_md5 TEXT);
        INSERT INTO research_snapshots VALUES('s1','t','source.csv','src1','m1');
        INSERT INTO research_experiments VALUES('e1','Experiment 1','DIAGNOSTIC','s1','COMPLETED','t','r1','72cf7d54e1ed6369400683358da8c0ef');
        ''')
    with sqlite3.connect(reviews) as c:
        c.executescript('''
        CREATE TABLE research_reviews(review_id TEXT,target_type TEXT,target_id TEXT,target_checksum TEXT,title TEXT,state TEXT,created_at TEXT,updated_at TEXT,created_by TEXT,engine_md5 TEXT);
        CREATE TABLE research_review_annotations(annotation_id TEXT,review_id TEXT);
        CREATE TABLE research_review_events(event_id TEXT,review_id TEXT);
        INSERT INTO research_reviews VALUES('rv1','EXPERIMENT','e1','r1','Review','APPROVED','t','t','auditor','72cf7d54e1ed6369400683358da8c0ef');
        ''')
    with sqlite3.connect(ledger) as c:
        c.executescript('''
        CREATE TABLE governance_incidents(incident_id INTEGER,code TEXT,severity TEXT,target_type TEXT,target_id TEXT,state TEXT,first_seen TEXT,last_seen TEXT,resolved_at TEXT,occurrence_count INTEGER,detail_json TEXT,fingerprint TEXT,engine_md5 TEXT);
        CREATE TABLE governance_incident_events(event_id INTEGER,incident_id INTEGER,event_at TEXT,event_type TEXT,from_state TEXT,to_state TEXT,detail_json TEXT,event_sha256 TEXT);
        CREATE TABLE governance_alert_state(incident_id INTEGER,current_level TEXT,previous_level TEXT,policy_version TEXT,first_alerted TEXT,last_evaluated TEXT,last_changed TEXT,reason_json TEXT,active INTEGER);
        CREATE TABLE governance_alert_events(alert_event_id INTEGER,incident_id INTEGER,event_at TEXT,event_type TEXT,from_level TEXT,to_level TEXT,reason_json TEXT,event_sha256 TEXT);
        INSERT INTO governance_incidents VALUES(1,'MISSING_REVIEW','WARNING','COHORT','c1','NEW','t','t',NULL,1,'{}','f','72cf7d54e1ed6369400683358da8c0ef');
        ''')
    return workspace, reviews, ledger


def test_bundle_is_self_verifying_and_contains_required_evidence(tmp_path):
    workspace, reviews, ledger = _fixtures(tmp_path)
    service = ResearchGovernanceAuditBundleService(str(workspace), str(reviews), str(ledger))
    output = tmp_path / 'audit.zip'
    result = service.export_bundle(str(output))
    assert result['sha256'] == _sha(output)
    verified = service.verify_bundle(str(output))
    assert verified['valid'] is True
    with zipfile.ZipFile(output) as z:
        names = set(z.namelist())
        assert {'manifest.json','index.html','verify_bundle.py','reports/governance_coverage.json','reports/lineage_provenance.json','reports/governance_ledger.json'} <= names
        manifest = json.loads(z.read('manifest.json'))
        assert manifest['engine_md5'] == ENGINE_MD5
        assert manifest['boundary']['source_databases_read_only'] is True


def test_export_does_not_modify_source_databases(tmp_path):
    workspace, reviews, ledger = _fixtures(tmp_path)
    before = [_sha(x) for x in (workspace, reviews, ledger)]
    ResearchGovernanceAuditBundleService(str(workspace), str(reviews), str(ledger)).export_bundle(str(tmp_path/'audit.zip'))
    assert before == [_sha(x) for x in (workspace, reviews, ledger)]


def test_verifier_detects_tampered_payload(tmp_path):
    workspace, reviews, ledger = _fixtures(tmp_path)
    service = ResearchGovernanceAuditBundleService(str(workspace), str(reviews), str(ledger))
    original = tmp_path/'audit.zip'; service.export_bundle(str(original))
    tampered = tmp_path/'tampered.zip'
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(tampered, 'w') as target:
        for name in source.namelist():
            data = source.read(name)
            if name == 'reports/governance_coverage.json': data += b'X'
            target.writestr(name, data)
    result = service.verify_bundle(str(tampered))
    assert result['valid'] is False
    assert any('checksum mismatch' in x for x in result['errors'])


def test_manifest_records_source_hashes_and_frozen_engine(tmp_path):
    workspace, reviews, ledger = _fixtures(tmp_path)
    service = ResearchGovernanceAuditBundleService(str(workspace), str(reviews), str(ledger))
    _, manifest = service.build_payloads()
    assert manifest['source_database_hashes']['workspace'] == _sha(workspace)
    assert manifest['source_database_hashes']['reviews'] == _sha(reviews)
    assert manifest['source_database_hashes']['ledger'] == _sha(ledger)
    assert manifest['engine_md5'] == '72cf7d54e1ed6369400683358da8c0ef'
