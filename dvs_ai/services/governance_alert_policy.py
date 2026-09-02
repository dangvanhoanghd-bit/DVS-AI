from __future__ import annotations

import hashlib, html, json, sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dvs_ai.services.governance_incident_ledger import GovernanceIncidentLedgerService, ENGINE_MD5

POLICY_VERSION = '4.2.0-J-policy-1'
LEVEL_ORDER = {'NONE':0,'NOTICE':1,'WATCH':2,'ALERT':3,'URGENT':4}


def _now(): return datetime.now(timezone.utc).isoformat()
def _canonical(v: Any): return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',',':'))
def _sha(v: Any): return hashlib.sha256(_canonical(v).encode()).hexdigest()


class GovernanceAlertPolicyService:
    """Deterministic alert policy and compliance operations snapshot."""
    def __init__(self, workspace='data/research_workspace.db', reviews='data/research_reviews.db', ledger='data/research_governance_ledger.db'):
        self.incidents = GovernanceIncidentLedgerService(workspace, reviews, ledger)
        self.ledger = Path(ledger); self._schema()

    def _connect(self):
        c=sqlite3.connect(self.ledger); c.row_factory=sqlite3.Row; return c

    def _schema(self):
        with self._connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS governance_alert_state(
              incident_id INTEGER PRIMARY KEY, current_level TEXT NOT NULL, previous_level TEXT NOT NULL,
              policy_version TEXT NOT NULL, first_alerted TEXT, last_evaluated TEXT NOT NULL,
              last_changed TEXT NOT NULL, reason_json TEXT NOT NULL, active INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS governance_alert_events(
              alert_event_id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER NOT NULL,
              event_at TEXT NOT NULL, event_type TEXT NOT NULL, from_level TEXT NOT NULL,
              to_level TEXT NOT NULL, reason_json TEXT NOT NULL, event_sha256 TEXT NOT NULL);
            ''')

    @staticmethod
    def classify(incident: dict[str,Any]) -> tuple[str,dict[str,Any]]:
        if incident['state']=='RESOLVED': return 'NONE', {'rule':'resolved'}
        code=incident['code']; severity=incident['severity']; n=int(incident.get('occurrence_count',1))
        if code=='APPROVED_ARTIFACT_DRIFT': level='URGENT'
        elif severity=='CRITICAL': level='URGENT'
        elif severity=='ERROR': level='ALERT'
        elif severity=='WARNING': level='WATCH' if n>=3 else 'NOTICE'
        else: level='NOTICE' if n>=5 else 'NONE'
        return level, {'rule':'deterministic severity/code policy','code':code,'severity':severity,'occurrences':n}

    def evaluate(self, scan=False):
        scan_result=self.incidents.scan() if scan else None
        incidents=self.incidents.list_incidents(True); now=_now(); changes=[]
        with self._connect() as c:
            old={r['incident_id']:dict(r) for r in c.execute('SELECT * FROM governance_alert_state')}
            for x in incidents:
                new,reason=self.classify(x); prior=old.get(x['incident_id']); prev=prior['current_level'] if prior else 'NONE'
                if new==prev: event='ONGOING' if new!='NONE' else 'CLEARED'
                elif new=='NONE': event='CLEARED'
                elif prev=='NONE': event='NEW'
                elif LEVEL_ORDER[new]>LEVEL_ORDER[prev]: event='ESCALATED'
                else: event='DEESCALATED'
                first=(prior or {}).get('first_alerted') or (now if new!='NONE' else None)
                changed=now if new!=prev or not prior else prior['last_changed']
                c.execute('''INSERT INTO governance_alert_state(incident_id,current_level,previous_level,policy_version,first_alerted,last_evaluated,last_changed,reason_json,active)
                  VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(incident_id) DO UPDATE SET current_level=excluded.current_level,previous_level=excluded.previous_level,policy_version=excluded.policy_version,first_alerted=excluded.first_alerted,last_evaluated=excluded.last_evaluated,last_changed=excluded.last_changed,reason_json=excluded.reason_json,active=excluded.active''',
                  (x['incident_id'],new,prev,POLICY_VERSION,first,now,changed,_canonical(reason),int(new!='NONE')))
                if new!=prev:
                    payload={'incident_id':x['incident_id'],'event':event,'from':prev,'to':new,'reason':reason}
                    c.execute('INSERT INTO governance_alert_events(incident_id,event_at,event_type,from_level,to_level,reason_json,event_sha256) VALUES(?,?,?,?,?,?,?)',
                              (x['incident_id'],now,event,prev,new,_canonical(reason),_sha(payload)))
                    changes.append(payload)
        return {'generated_at':now,'scan':scan_result,'changes':changes,'snapshot':self.snapshot()}

    def snapshot(self):
        incidents={x['incident_id']:x for x in self.incidents.list_incidents(True)}
        with self._connect() as c:
            states=[dict(r) for r in c.execute('SELECT * FROM governance_alert_state ORDER BY active DESC, CASE current_level WHEN "URGENT" THEN 4 WHEN "ALERT" THEN 3 WHEN "WATCH" THEN 2 WHEN "NOTICE" THEN 1 ELSE 0 END DESC,last_changed DESC')]
            events=[dict(r) for r in c.execute('SELECT * FROM governance_alert_events ORDER BY alert_event_id DESC LIMIT 200')]
        rows=[]
        for s in states:
            x=incidents.get(s['incident_id'],{}); rows.append({**x,'alert_level':s['current_level'],'previous_level':s['previous_level'],'policy_version':s['policy_version'],'reason':json.loads(s['reason_json']),'alert_active':bool(s['active']),'last_changed':s['last_changed']})
        counts=Counter(x['alert_level'] for x in rows if x['alert_active'])
        status=max(counts, key=lambda k:LEVEL_ORDER[k]) if counts else 'NONE'
        return {'policy_version':POLICY_VERSION,'generated_at':_now(),'status':status,'level_counts':dict(counts),'incidents':rows,'events':events,'engine_md5':ENGINE_MD5,'boundary':{'automatic_remediation':False,'source_databases_read_only':True,'decision_engine_invocation':False}}

    def export_json(self,path):
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(self.snapshot(),ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8'); return str(p)
    def export_html(self,path):
        r=self.snapshot(); rows=''.join(f"<tr><td>{html.escape(x['alert_level'])}</td><td>{html.escape(x.get('severity',''))}</td><td>{html.escape(x.get('code',''))}</td><td>{html.escape(x.get('target_type',''))}</td><td>{html.escape(x.get('target_id',''))}</td><td>{html.escape(x.get('state',''))}</td></tr>" for x in r['incidents']) or '<tr><td colspan=6>None</td></tr>'
        body=f'''<!doctype html><meta charset="utf-8"><title>Compliance Operations</title><h1>Governance Alert Policy & Compliance Operations</h1><p>Status: {r['status']} · Policy: {r['policy_version']}</p><table border="1" cellpadding="6"><tr><th>Alert</th><th>Severity</th><th>Code</th><th>Type</th><th>ID</th><th>State</th></tr>{rows}</table><p><strong>Boundary:</strong> read-only source inspection; no automatic remediation; no Decision Engine invocation.</p>'''
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(body,encoding='utf-8'); return str(p)
