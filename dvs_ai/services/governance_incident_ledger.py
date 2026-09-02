from __future__ import annotations

import hashlib, html, json, sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dvs_ai.services.research_governance_dashboard import ResearchGovernanceDashboardService, ENGINE_MD5

SCHEMA_VERSION = 'governance-incident-ledger-v1'
SEVERITY_ORDER = {'CRITICAL': 4, 'ERROR': 3, 'WARNING': 2, 'INFO': 1}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _sha(v: Any) -> str:
    return hashlib.sha256(_canonical(v).encode('utf-8')).hexdigest()


class GovernanceIncidentLedgerService:
    """Deterministic governance exception ledger; source databases remain read-only."""

    def __init__(self, workspace_path='data/research_workspace.db', review_db_path='data/research_reviews.db', ledger_path='data/research_governance_ledger.db'):
        self.workspace = Path(workspace_path); self.review_db = Path(review_db_path); self.ledger = Path(ledger_path)
        self.ledger.parent.mkdir(parents=True, exist_ok=True); self._schema()

    def _connect(self):
        c = sqlite3.connect(self.ledger); c.row_factory = sqlite3.Row; return c

    def _schema(self):
        with self._connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS governance_incidents(
              incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
              code TEXT NOT NULL, severity TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
              state TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, resolved_at TEXT,
              occurrence_count INTEGER NOT NULL, detail_json TEXT NOT NULL, fingerprint TEXT NOT NULL,
              engine_md5 TEXT NOT NULL, UNIQUE(code,target_type,target_id));
            CREATE TABLE IF NOT EXISTS governance_incident_events(
              event_id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER NOT NULL, event_at TEXT NOT NULL,
              event_type TEXT NOT NULL, from_state TEXT, to_state TEXT NOT NULL, detail_json TEXT NOT NULL,
              event_sha256 TEXT NOT NULL);
            ''')

    @staticmethod
    def _candidate(code, severity, target_type, target_id, detail):
        identity = {'code': code, 'target_type': target_type, 'target_id': str(target_id)}
        return {**identity, 'severity': severity, 'detail': detail, 'fingerprint': _sha({**identity, 'detail': detail})}

    def detect(self) -> list[dict[str, Any]]:
        report = ResearchGovernanceDashboardService(self.workspace, self.review_db).analyze()
        out = []
        for x in report['unreviewed_targets']:
            out.append(self._candidate('MISSING_REVIEW', 'WARNING', x['target_type'], x['target_id'], {'title': x.get('title','')}))
        for x in report['stale_reviews']:
            sev = 'CRITICAL' if x.get('state') == 'APPROVED' else 'ERROR'
            out.append(self._candidate('REVIEW_CHECKSUM_DRIFT', sev, x['target_type'], x['target_id'], x))
            if x.get('state') == 'APPROVED':
                out.append(self._candidate('APPROVED_ARTIFACT_DRIFT', 'CRITICAL', x['target_type'], x['target_id'], x))
        for x in report['orphan_reviews']:
            out.append(self._candidate('ORPHAN_REVIEW', 'ERROR', x.get('target_type','UNKNOWN'), x.get('target_id','UNKNOWN'), x))
        for x in report['engine_mismatch_reviews']:
            out.append(self._candidate('REVIEW_ENGINE_MD5_MISMATCH', 'CRITICAL', 'REVIEW', x['review_id'], x))
        return sorted(out, key=lambda x: (-SEVERITY_ORDER[x['severity']], x['code'], x['target_type'], x['target_id']))

    def _event(self, c, incident_id, event_type, from_state, to_state, detail):
        payload = {'incident_id': incident_id, 'event_type': event_type, 'from_state': from_state, 'to_state': to_state, 'detail': detail}
        c.execute('INSERT INTO governance_incident_events(incident_id,event_at,event_type,from_state,to_state,detail_json,event_sha256) VALUES(?,?,?,?,?,?,?)',
                  (incident_id, _now(), event_type, from_state, to_state, _canonical(detail), _sha(payload)))

    def scan(self) -> dict[str, Any]:
        candidates = self.detect(); now = _now(); active_keys = {(x['code'],x['target_type'],x['target_id']) for x in candidates}
        counts = Counter()
        with self._connect() as c:
            existing = {(r['code'],r['target_type'],r['target_id']): dict(r) for r in c.execute('SELECT * FROM governance_incidents')}
            for x in candidates:
                key=(x['code'],x['target_type'],x['target_id']); old=existing.get(key)
                if old is None:
                    c.execute('INSERT INTO governance_incidents(code,severity,target_type,target_id,state,first_seen,last_seen,resolved_at,occurrence_count,detail_json,fingerprint,engine_md5) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                              (x['code'],x['severity'],x['target_type'],x['target_id'],'NEW',now,now,None,1,_canonical(x['detail']),x['fingerprint'],ENGINE_MD5))
                    iid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; self._event(c,iid,'NEW',None,'NEW',x['detail']); counts['new']+=1
                else:
                    from_state=old['state']; to_state='REOPENED' if from_state=='RESOLVED' else 'ONGOING'
                    c.execute('UPDATE governance_incidents SET severity=?,state=?,last_seen=?,resolved_at=NULL,occurrence_count=occurrence_count+1,detail_json=?,fingerprint=? WHERE incident_id=?',
                              (x['severity'],to_state,now,_canonical(x['detail']),x['fingerprint'],old['incident_id']))
                    self._event(c,old['incident_id'],to_state,from_state,to_state,x['detail']); counts[to_state.lower()]+=1
            for key, old in existing.items():
                if key not in active_keys and old['state']!='RESOLVED':
                    c.execute("UPDATE governance_incidents SET state='RESOLVED',last_seen=?,resolved_at=? WHERE incident_id=?",(now,now,old['incident_id']))
                    self._event(c,old['incident_id'],'RESOLVED',old['state'],'RESOLVED',{'reason':'exception no longer detected'}); counts['resolved']+=1
        return {'generated_at': now, 'detected': len(candidates), 'transitions': dict(counts), 'engine_md5': ENGINE_MD5}

    def list_incidents(self, include_resolved=True):
        q='SELECT * FROM governance_incidents' + ('' if include_resolved else " WHERE state!='RESOLVED'") + ' ORDER BY CASE severity WHEN \'CRITICAL\' THEN 4 WHEN \'ERROR\' THEN 3 WHEN \'WARNING\' THEN 2 ELSE 1 END DESC,last_seen DESC'
        with self._connect() as c:
            rows=[dict(r) for r in c.execute(q)]
        for r in rows: r['detail']=json.loads(r.pop('detail_json'))
        return rows

    def report(self):
        incidents=self.list_incidents(True); active=[x for x in incidents if x['state']!='RESOLVED']
        out={'schema':SCHEMA_VERSION,'generated_at':_now(),'engine_md5':ENGINE_MD5,'summary':{'total':len(incidents),'active':len(active),'resolved':len(incidents)-len(active),'severity_counts':dict(Counter(x['severity'] for x in active))},'incidents':incidents,'scientific_boundary':{'source_databases_read_only':True,'automatic_remediation':False,'decision_engine_invocation':False,'canonical_database_write':False}}
        out['report_sha256']=_sha(out); return out

    def export_json(self,path):
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(self.report(),ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8'); return str(p)

    def export_html(self,path):
        r=self.report(); rows=''.join(f"<tr><td>{html.escape(x['severity'])}</td><td>{html.escape(x['code'])}</td><td>{html.escape(x['target_type'])}</td><td>{html.escape(x['target_id'])}</td><td>{html.escape(x['state'])}</td><td>{x['occurrence_count']}</td></tr>" for x in r['incidents']) or '<tr><td colspan=6>None</td></tr>'
        body=f'''<!doctype html><meta charset="utf-8"><title>Governance Incident Ledger</title><h1>Governance Incident & Compliance Exceptions Ledger</h1><p>Generated: {html.escape(r['generated_at'])}</p><p>Active: {r['summary']['active']} · Resolved: {r['summary']['resolved']}</p><table border="1" cellpadding="6"><tr><th>Severity</th><th>Code</th><th>Type</th><th>ID</th><th>State</th><th>Occurrences</th></tr>{rows}</table><p><strong>Boundary:</strong> read-only source inspection; no automatic remediation; no Decision Engine invocation.</p>'''
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(body,encoding='utf-8'); return str(p)
