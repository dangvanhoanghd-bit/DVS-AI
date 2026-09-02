import sqlite3
from dvs_ai.services.governance_alert_policy import GovernanceAlertPolicyService, POLICY_VERSION
from dvs_ai.services.governance_incident_ledger import ENGINE_MD5


def build(tmp_path):
    w=tmp_path/'w.db'; r=tmp_path/'r.db'; l=tmp_path/'l.db'
    with sqlite3.connect(w) as c:
        c.execute('CREATE TABLE research_experiments(experiment_id TEXT PRIMARY KEY,name TEXT,result_sha256 TEXT)')
        c.execute('CREATE TABLE research_comparisons(comparison_id TEXT PRIMARY KEY,verdict TEXT,report_sha256 TEXT)')
        c.execute('CREATE TABLE research_cohorts(cohort_id TEXT PRIMARY KEY,name TEXT,summary_sha256 TEXT)')
        c.execute("INSERT INTO research_experiments VALUES('e1','E','good')")
    with sqlite3.connect(r) as c:
        c.execute('CREATE TABLE research_reviews(review_id TEXT PRIMARY KEY,target_type TEXT,target_id TEXT,target_checksum TEXT,title TEXT,state TEXT,created_at TEXT,updated_at TEXT,created_by TEXT,engine_md5 TEXT)')
        c.execute('CREATE TABLE research_review_annotations(annotation_id TEXT,review_id TEXT,created_at TEXT,author TEXT,category TEXT,note TEXT,note_sha256 TEXT)')
        c.execute('CREATE TABLE research_review_events(event_id INTEGER,review_id TEXT,event_at TEXT,event_type TEXT,actor TEXT,from_state TEXT,to_state TEXT,detail_json TEXT,event_sha256 TEXT)')
        c.execute("INSERT INTO research_reviews VALUES('r1','EXPERIMENT','e1','old','R','APPROVED','t','t','a',?)",(ENGINE_MD5,))
    return w,r,l


def test_critical_governance_incident_is_urgent(tmp_path):
    s=GovernanceAlertPolicyService(*build(tmp_path)); out=s.evaluate(True); rows=out['snapshot']['incidents']
    assert any(x['code']=='APPROVED_ARTIFACT_DRIFT' and x['alert_level']=='URGENT' for x in rows)
    assert out['snapshot']['policy_version']==POLICY_VERSION


def test_warning_missing_review_starts_notice(tmp_path):
    w,r,l=build(tmp_path)
    with sqlite3.connect(w) as c: c.execute("INSERT INTO research_experiments VALUES('e2','E2','x')")
    s=GovernanceAlertPolicyService(w,r,l); rows=s.evaluate(True)['snapshot']['incidents']
    assert any(x['code']=='MISSING_REVIEW' and x['alert_level']=='NOTICE' for x in rows)


def test_resolved_incident_clears_alert(tmp_path):
    w,r,l=build(tmp_path); s=GovernanceAlertPolicyService(w,r,l); s.evaluate(True)
    with sqlite3.connect(r) as c: c.execute("UPDATE research_reviews SET target_checksum='good' WHERE review_id='r1'")
    rows=s.evaluate(True)['snapshot']['incidents']
    drift=[x for x in rows if x['code']=='APPROVED_ARTIFACT_DRIFT'][0]
    assert drift['state']=='RESOLVED' and drift['alert_level']=='NONE'


def test_exports_disclose_boundary(tmp_path):
    s=GovernanceAlertPolicyService(*build(tmp_path)); s.evaluate(True)
    j=tmp_path/'a.json'; h=tmp_path/'a.html'; s.export_json(j); s.export_html(h)
    assert 'automatic_remediation' in j.read_text(encoding='utf-8')
    assert 'no automatic remediation' in h.read_text(encoding='utf-8').lower()
