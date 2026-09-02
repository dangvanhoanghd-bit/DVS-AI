import sqlite3
from dvs_ai.services.research_experiment_engine import ResearchExperimentEngine,ENGINE_MD5

def source(tmp_path):
 p=tmp_path/'source.db'
 with sqlite3.connect(p) as c:
  c.execute('create table observations(grp text,value real)'); c.executemany('insert into observations values(?,?)',[('A',1),('A',3),('B',10),('B',12)])
 return p

def test_profile_run_and_provenance(tmp_path):
 s=source(tmp_path); e=ResearchExperimentEngine(str(s),str(tmp_path/'research.db')); eid=e.register('profile','describe','DATASET_PROFILE'); r=e.run(eid)
 assert r['status']=='FINISHED' and r['engine_md5']==ENGINE_MD5 and r['result_sha256']
 assert r['result']['total_rows']==4

def test_group_comparison(tmp_path):
 s=source(tmp_path); e=ResearchExperimentEngine(str(s),str(tmp_path/'research.db')); eid=e.register('groups','compare','GROUP_COMPARISON',{'table':'observations','group_column':'grp','value_column':'value'}); r=e.run(eid)
 assert r['status']=='FINISHED' and len(r['result']['groups'])==2

def test_dataset_drift_blocks_run(tmp_path):
 s=source(tmp_path); e=ResearchExperimentEngine(str(s),str(tmp_path/'research.db')); eid=e.register('stable','locked','DATASET_PROFILE')
 with sqlite3.connect(s) as c:c.execute("insert into observations values('C',99)")
 assert e.run(eid)['status']=='BLOCKED_DATASET_DRIFT'

def test_rejects_unregistered_analysis(tmp_path):
 s=source(tmp_path); e=ResearchExperimentEngine(str(s),str(tmp_path/'research.db'))
 try:e.register('x','x','ARBITRARY_CODE')
 except ValueError:pass
 else:assert False
