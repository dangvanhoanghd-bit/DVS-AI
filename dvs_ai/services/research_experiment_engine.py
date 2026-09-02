from __future__ import annotations
import hashlib, json, math, sqlite3, statistics, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE_MD5='72cf7d54e1ed6369400683358da8c0ef'
SCHEMA_VERSION='research-execution-v1'
ALLOWED_ANALYSES={'DATASET_PROFILE','GROUP_COMPARISON','STABILITY_CHECK'}

def _now(): return datetime.now(timezone.utc).isoformat()
def _canonical(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def _sha(v): return hashlib.sha256(_canonical(v).encode()).hexdigest()

class ResearchExperimentEngine:
    """Deterministic, allow-listed research runner isolated from the Decision Engine."""
    def __init__(self, source_db_path: str, workspace_path: str='data/research_workspace.db'):
        self.source=Path(source_db_path); self.workspace=Path(workspace_path); self.workspace.parent.mkdir(parents=True,exist_ok=True); self._schema()
    def _connect(self):
        c=sqlite3.connect(self.workspace); c.row_factory=sqlite3.Row; return c
    def _schema(self):
        with self._connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS research_snapshots(snapshot_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,source_path TEXT NOT NULL,source_sha256 TEXT NOT NULL,manifest_json TEXT NOT NULL,manifest_sha256 TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_experiments(experiment_id TEXT PRIMARY KEY,name TEXT NOT NULL,hypothesis TEXT NOT NULL,analysis_type TEXT NOT NULL,parameters_json TEXT NOT NULL,snapshot_id TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,result_json TEXT,result_sha256 TEXT,error TEXT,engine_md5 TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_events(id INTEGER PRIMARY KEY AUTOINCREMENT,experiment_id TEXT NOT NULL,event_at TEXT NOT NULL,event_type TEXT NOT NULL,detail_json TEXT NOT NULL);
            ''')
    def _source_ro(self):
        if not self.source.exists(): raise FileNotFoundError(self.source)
        return sqlite3.connect(f'file:{self.source.resolve().as_posix()}?mode=ro',uri=True)
    def create_snapshot(self)->dict[str,Any]:
        raw=self.source.read_bytes(); source_sha=hashlib.sha256(raw).hexdigest(); tables=[]
        with self._source_ro() as c:
            names=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            for name in names:
                safe=name.replace('"','""'); count=c.execute(f'SELECT COUNT(*) FROM "{safe}"').fetchone()[0]
                cols=[r[1] for r in c.execute(f'PRAGMA table_info("{safe}")')]
                tables.append({'name':name,'row_count':count,'columns':cols})
        manifest={'schema':'research-dataset-snapshot-v1','source_path':str(self.source),'source_sha256':source_sha,'tables':tables,'engine_md5':ENGINE_MD5}
        sid=str(uuid.uuid4()); msha=_sha(manifest)
        with self._connect() as c:c.execute('INSERT INTO research_snapshots VALUES(?,?,?,?,?,?)',(sid,_now(),str(self.source),source_sha,_canonical(manifest),msha))
        return {'snapshot_id':sid,'manifest':manifest,'manifest_sha256':msha}
    def register(self,name:str,hypothesis:str,analysis_type:str,parameters:dict[str,Any]|None=None,snapshot_id:str|None=None)->str:
        if analysis_type not in ALLOWED_ANALYSES: raise ValueError('Analysis type is not allow-listed')
        if not snapshot_id: snapshot_id=self.create_snapshot()['snapshot_id']
        eid=str(uuid.uuid4()); now=_now()
        with self._connect() as c:
            c.execute('INSERT INTO research_experiments(experiment_id,name,hypothesis,analysis_type,parameters_json,snapshot_id,status,created_at,engine_md5) VALUES(?,?,?,?,?,?,?,?,?)',(eid,name.strip() or analysis_type,hypothesis.strip(),analysis_type,_canonical(parameters or {}),snapshot_id,'CREATED',now,ENGINE_MD5))
            c.execute('INSERT INTO research_events(experiment_id,event_at,event_type,detail_json) VALUES(?,?,?,?)',(eid,now,'CREATED','{}'))
        return eid
    def _snapshot(self,c,sid):
        r=c.execute('SELECT * FROM research_snapshots WHERE snapshot_id=?',(sid,)).fetchone()
        if not r: raise KeyError('Snapshot not found')
        return dict(r)
    def _numeric_values(self,table,column)->list[float]:
        safe_t=table.replace('"','""'); safe_c=column.replace('"','""')
        with self._source_ro() as c:
            vals=[]
            for (v,) in c.execute(f'SELECT "{safe_c}" FROM "{safe_t}" WHERE "{safe_c}" IS NOT NULL'):
                try:
                    x=float(v)
                    if math.isfinite(x): vals.append(x)
                except (TypeError,ValueError): pass
            return vals
    def _execute(self,kind,p):
        if kind=='DATASET_PROFILE':
            with self._source_ro() as c:
                out=[]
                for (n,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
                    safe=n.replace('"','""'); out.append({'table':n,'rows':c.execute(f'SELECT COUNT(*) FROM "{safe}"').fetchone()[0]})
            return {'analysis':kind,'tables':out,'total_rows':sum(x['rows'] for x in out)}
        if kind=='STABILITY_CHECK':
            vals=self._numeric_values(str(p['table']),str(p['column']))
            n=len(vals); mid=n//2; a,b=vals[:mid],vals[mid:]
            mean=lambda x: statistics.fmean(x) if x else None
            return {'analysis':kind,'n':n,'first_half_mean':mean(a),'second_half_mean':mean(b),'absolute_drift':None if not a or not b else abs(mean(a)-mean(b)),'stable_interpretation':'descriptive_only'}
        group_col=str(p['group_column']); value_col=str(p['value_column']); table=str(p['table']); safe_t=table.replace('"','""'); safe_g=group_col.replace('"','""'); safe_v=value_col.replace('"','""'); groups={}
        with self._source_ro() as c:
            for g,v in c.execute(f'SELECT "{safe_g}","{safe_v}" FROM "{safe_t}" WHERE "{safe_v}" IS NOT NULL'):
                try: groups.setdefault(str(g),[]).append(float(v))
                except (TypeError,ValueError): pass
        return {'analysis':kind,'groups':[{'group':g,'n':len(v),'mean':statistics.fmean(v),'median':statistics.median(v)} for g,v in sorted(groups.items()) if v]}
    def run(self,experiment_id:str)->dict[str,Any]:
        with self._connect() as c:
            r=c.execute('SELECT * FROM research_experiments WHERE experiment_id=?',(experiment_id,)).fetchone()
            if not r: raise KeyError('Experiment not found')
            e=dict(r); s=self._snapshot(c,e['snapshot_id']); current=hashlib.sha256(self.source.read_bytes()).hexdigest()
            if current!=s['source_sha256']:
                now=_now(); c.execute('UPDATE research_experiments SET status=?,finished_at=?,error=? WHERE experiment_id=?',('BLOCKED_DATASET_DRIFT',now,'Source checksum differs from locked snapshot',experiment_id)); c.execute('INSERT INTO research_events(experiment_id,event_at,event_type,detail_json) VALUES(?,?,?,?)',(experiment_id,now,'BLOCKED_DATASET_DRIFT',_canonical({'expected':s['source_sha256'],'actual':current}))); c.commit()
                return self.get(experiment_id)
            started=_now(); c.execute('UPDATE research_experiments SET status=?,started_at=? WHERE experiment_id=?',('RUNNING',started,experiment_id)); c.execute('INSERT INTO research_events(experiment_id,event_at,event_type,detail_json) VALUES(?,?,?,?)',(experiment_id,started,'RUNNING','{}'))
        try:
            result=self._execute(e['analysis_type'],json.loads(e['parameters_json'])); finished=_now(); digest=_sha(result)
            with self._connect() as c:
                c.execute('UPDATE research_experiments SET status=?,finished_at=?,result_json=?,result_sha256=? WHERE experiment_id=?',('FINISHED',finished,_canonical(result),digest,experiment_id)); c.execute('INSERT INTO research_events(experiment_id,event_at,event_type,detail_json) VALUES(?,?,?,?)',(experiment_id,finished,'FINISHED',_canonical({'result_sha256':digest})))
        except Exception as exc:
            with self._connect() as c:
                c.execute('UPDATE research_experiments SET status=?,finished_at=?,error=? WHERE experiment_id=?',('FAILED',_now(),f'{type(exc).__name__}: {exc}',experiment_id))
        return self.get(experiment_id)
    def get(self,eid):
        with self._connect() as c:
            r=c.execute('SELECT * FROM research_experiments WHERE experiment_id=?',(eid,)).fetchone(); d=dict(r) if r else None
            if not d:return None
            for k,out in (('parameters_json','parameters'),('result_json','result')):
                if d.get(k): d[out]=json.loads(d[k])
            d['events']=[dict(x) for x in c.execute('SELECT event_at,event_type,detail_json FROM research_events WHERE experiment_id=? ORDER BY id',(eid,))]
            return d
    def list_experiments(self):
        with self._connect() as c:return [dict(r) for r in c.execute('SELECT experiment_id,name,analysis_type,status,created_at,finished_at,result_sha256 FROM research_experiments ORDER BY created_at DESC')]
