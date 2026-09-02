import hashlib, sqlite3
from pathlib import Path
from dvs_ai.services.governance_incident_ledger import GovernanceIncidentLedgerService, ENGINE_MD5


def build(tmp_path):
    w=tmp_path/'workspace.db'; r=tmp_path/'reviews.db'; l=tmp_path/'ledger.db'
    with sqlite3.connect(w) as c:
        c.execute('CREATE TABLE research_experiments(experiment_id TEXT PRIMARY KEY,name TEXT,result_sha256 TEXT)')
        c.execute('CREATE TABLE research_comparisons(comparison_id TEXT PRIMARY KEY,verdict TEXT,report_sha256 TEXT)')
        c.execute('CREATE TABLE research_cohorts(cohort_id TEXT PRIMARY KEY,name TEXT,summary_sha256 TEXT)')
        c.execute("INSERT INTO research_experiments VALUES('e1','Experiment 1','good')")
        c.execute("INSERT INTO research_experiments VALUES('e2','Experiment 2','e2sum')")
    with sqlite3.connect(r) as c:
        c.execute('CREATE TABLE research_reviews(review_id TEXT PRIMARY KEY,target_type TEXT,target_id TEXT,target_checksum TEXT,title TEXT,state TEXT,created_at TEXT,updated_at TEXT,created_by TEXT,engine_md5 TEXT)')
        c.execute('CREATE TABLE research_review_annotations(annotation_id TEXT,review_id TEXT,created_at TEXT,author TEXT,category TEXT,note TEXT,note_sha256 TEXT)')
        c.execute('CREATE TABLE research_review_events(event_id INTEGER,review_id TEXT,event_at TEXT,event_type TEXT,actor TEXT,from_state TEXT,to_state TEXT,detail_json TEXT,event_sha256 TEXT)')
        c.execute("INSERT INTO research_reviews VALUES('r1','EXPERIMENT','e1','old','R','APPROVED','t','t','alice',?)",(ENGINE_MD5,))
        c.execute("INSERT INTO research_reviews VALUES('r2','EXPERIMENT','missing','x','R','IN_REVIEW','t','t','bob',?)",(ENGINE_MD5,))
        c.execute("INSERT INTO research_reviews VALUES('r3','EXPERIMENT','e2','e2sum','R','IN_REVIEW','t','t','bob','bad-md5')")
    return w,r,l


def test_detects_compliance_exceptions(tmp_path):
    w,r,l=build(tmp_path); s=GovernanceIncidentLedgerService(w,r,l); codes=[x['code'] for x in s.detect()]
    assert 'REVIEW_CHECKSUM_DRIFT' in codes
    assert 'APPROVED_ARTIFACT_DRIFT' in codes
    assert 'ORPHAN_REVIEW' in codes
    assert 'REVIEW_ENGINE_MD5_MISMATCH' in codes


def test_lifecycle_resolves_and_reopens(tmp_path):
    w,r,l=build(tmp_path); s=GovernanceIncidentLedgerService(w,r,l); s.scan()
    with sqlite3.connect(r) as c: c.execute("UPDATE research_reviews SET target_checksum='good' WHERE review_id='r1'")
    s.scan(); drift=[x for x in s.list_incidents() if x['code']=='APPROVED_ARTIFACT_DRIFT'][0]; assert drift['state']=='RESOLVED'
    with sqlite3.connect(r) as c: c.execute("UPDATE research_reviews SET target_checksum='wrong' WHERE review_id='r1'")
    s.scan(); drift=[x for x in s.list_incidents() if x['code']=='APPROVED_ARTIFACT_DRIFT'][0]; assert drift['state']=='REOPENED'


def test_sources_are_not_modified(tmp_path):
    w,r,l=build(tmp_path)
    before=(hashlib.sha256(w.read_bytes()).hexdigest(),hashlib.sha256(r.read_bytes()).hexdigest())
    GovernanceIncidentLedgerService(w,r,l).scan()
    after=(hashlib.sha256(w.read_bytes()).hexdigest(),hashlib.sha256(r.read_bytes()).hexdigest())
    assert before==after


def test_exports(tmp_path):
    w,r,l=build(tmp_path); s=GovernanceIncidentLedgerService(w,r,l); s.scan()
    jp=tmp_path/'r.json'; hp=tmp_path/'r.html'; s.export_json(jp); s.export_html(hp)
    assert 'automatic_remediation' in jp.read_text(encoding='utf-8')
    assert 'no automatic remediation' in hp.read_text(encoding='utf-8').lower()
