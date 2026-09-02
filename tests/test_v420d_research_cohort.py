import json, sqlite3
from dvs_ai.services.research_experiment_engine import ResearchExperimentEngine
from dvs_ai.services.research_cohort_service import ResearchCohortService, ENGINE_MD5

def source(tmp_path):
 p=tmp_path/'source.db'
 with sqlite3.connect(p) as c:
  c.execute('create table observations(grp text,value real)'); c.executemany('insert into observations values(?,?)',[('A',1),('A',3),('B',10),('B',12)])
 return p

def make_ids(s,w,n=3):
 e=ResearchExperimentEngine(str(s),str(w)); snap=e.create_snapshot()['snapshot_id']; ids=[]
 for i in range(n): ids.append(e.register(f'e{i}','profile','DATASET_PROFILE',{},snap))
 return ids

def test_cohort_runs_created_experiments(tmp_path):
 s=source(tmp_path); w=tmp_path/'research.db'; ids=make_ids(s,w); svc=ResearchCohortService(str(s),str(w)); cid=svc.create_cohort('batch','coverage',ids); summary=svc.run_cohort(cid)
 assert summary['status']=='FINISHED'; assert summary['completed_experiments']==3; assert summary['completion_rate']==1.0
 assert summary['scientific_boundary']['decision_engine_invocation'] is False

def test_cohort_preserves_failed_or_blocked_status(tmp_path):
 s=source(tmp_path); w=tmp_path/'research.db'; ids=make_ids(s,w,2)
 with sqlite3.connect(w) as c: c.execute("update research_experiments set status='FAILED', error='fixture' where experiment_id=?",(ids[0],))
 svc=ResearchCohortService(str(s),str(w)); summary=svc.run_cohort(svc.create_cohort('x','y',ids))
 assert summary['status']=='COMPLETED_WITH_EXCEPTIONS'; assert summary['status_counts']['FAILED']==1

def test_cohort_registry_and_checksums(tmp_path):
 s=source(tmp_path); w=tmp_path/'research.db'; ids=make_ids(s,w,2); svc=ResearchCohortService(str(s),str(w)); cid=svc.create_cohort('x','y',ids); summary=svc.run_cohort(cid); row=svc.get_cohort(cid)
 assert row['engine_md5']==ENGINE_MD5; assert len(row['configuration_sha256'])==64; assert row['summary_sha256']==summary['summary_sha256']; assert len(row['events'])==3

def test_cohort_exports(tmp_path):
 s=source(tmp_path); w=tmp_path/'research.db'; ids=make_ids(s,w,2); svc=ResearchCohortService(str(s),str(w)); summary=svc.run_cohort(svc.create_cohort('x','y',ids)); jp=tmp_path/'c.json'; hp=tmp_path/'c.html'; svc.export_json(summary,str(jp)); svc.export_html(summary,str(hp))
 assert json.loads(jp.read_text())['total_experiments']==2; assert 'no Decision Engine invocation' in hp.read_text()
