import json, sqlite3
from dvs_ai.services.research_experiment_engine import ResearchExperimentEngine
from dvs_ai.services.research_reproducibility import ExperimentComparisonService, ENGINE_MD5

def source(tmp_path):
 p=tmp_path/'source.db'
 with sqlite3.connect(p) as c:
  c.execute('create table observations(grp text,value real)'); c.executemany('insert into observations values(?,?)',[('A',1),('A',3),('B',10),('B',12)])
 return p

def test_reproducible_same_snapshot(tmp_path):
 s=source(tmp_path); w=tmp_path/'research.db'; e=ResearchExperimentEngine(str(s),str(w)); snap=e.create_snapshot()['snapshot_id']
 a=e.register('a','x','DATASET_PROFILE',{},snap); b=e.register('b','x','DATASET_PROFILE',{},snap); e.run(a); e.run(b)
 r=ExperimentComparisonService(str(w)).compare([a,b])
 assert r['verdict']=='REPRODUCIBLE' and r['reproducible'] and r['checks']['same_result_sha256']
 assert all(x['engine_md5']==ENGINE_MD5 for x in r['runs'])

def test_parameter_drift(tmp_path):
 s=source(tmp_path); w=tmp_path/'research.db'; e=ResearchExperimentEngine(str(s),str(w)); snap=e.create_snapshot()['snapshot_id']
 a=e.register('a','x','STABILITY_CHECK',{'table':'observations','column':'value'},snap)
 b=e.register('b','x','STABILITY_CHECK',{'table':'observations','column':'value','note':'different'},snap); e.run(a); e.run(b)
 assert ExperimentComparisonService(str(w)).compare([a,b])['verdict']=='PARAMETER_DRIFT'

def test_dataset_drift_between_snapshots(tmp_path):
 s=source(tmp_path); w=tmp_path/'research.db'; e=ResearchExperimentEngine(str(s),str(w)); a=e.register('a','x','DATASET_PROFILE'); e.run(a)
 b=e.register('b','x','DATASET_PROFILE'); e.run(b)
 assert ExperimentComparisonService(str(w)).compare([a,b])['verdict']=='DATASET_DRIFT'

def test_exports(tmp_path):
 s=source(tmp_path); w=tmp_path/'research.db'; e=ResearchExperimentEngine(str(s),str(w)); snap=e.create_snapshot()['snapshot_id']; ids=[]
 for n in ('a','b'):
  x=e.register(n,'x','DATASET_PROFILE',{},snap); e.run(x); ids.append(x)
 svc=ExperimentComparisonService(str(w)); r=svc.compare(ids); jp=tmp_path/'r.json'; hp=tmp_path/'r.html'; svc.export_json(r,str(jp)); svc.export_html(r,str(hp))
 assert json.loads(jp.read_text())['verdict']=='REPRODUCIBLE'; assert 'no Decision Engine invocation' in hp.read_text()
