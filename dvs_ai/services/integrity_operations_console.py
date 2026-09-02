from __future__ import annotations
import html, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from dvs_ai.services.integrity_incident_ledger import IntegrityIncidentLedger
from dvs_ai.services.integrity_alert_policy import IntegrityAlertPolicy

class IntegrityOperationsConsoleService:
    SCHEMA_VERSION = 'integrity-operations-console-v1'
    def __init__(self, source_db_path: str, ledger_path: str='data/dvs_integrity_ledger.db') -> None:
        self.ledger = IntegrityIncidentLedger(source_db_path, ledger_path)
        self.policy = IntegrityAlertPolicy(ledger_path)
    @staticmethod
    def guidance(code: str) -> list[str]:
        mapping = {
          'MISSING_DIAGNOSTIC_TRACE':['Verify capture logs for the evaluation.','Compare evaluation timestamp with application shutdown or queue pressure.','Restore only from an authenticated backup; never fabricate a trace.'],
          'ORPHAN_EVALUATION':['Confirm the parent episode was not removed externally.','Preserve a database copy before any manual repair.','Escalate for forensic review; do not auto-link by similarity.'],
          'ORPHAN_CANDIDATE':['Confirm episode_id against immutable audit exports.','Do not create a replacement episode automatically.'],
          'ORPHAN_OUTCOME':['Confirm candidate_id against resolver logs and backups.','Do not attach the outcome to a guessed candidate.'],
          'PROFILE_HASH_MISMATCH':['Compare release manifest and frozen engine hash.','Quarantine the affected observation from scientific summaries until explained.'],
          'TRACE_HASH_MISMATCH':['Compare the stored trace profile hash with its episode.','Treat the trace as provenance-uncertain until reviewed.'],
          'SEQUENCE_GAP':['Inspect capture runner logs and queue metrics.','Do not renumber existing evaluations.'],
          'DUPLICATE_ACTIVATION':['Review activation timestamps and candidate IDs.','Do not delete either candidate before preserving evidence.'],
          'STALE_OPEN_EPISODE':['Check whether new evaluations are still arriving.','Close only through an approved manual procedure after review.'],
          'OVERDUE_WAITING_ENTRY':['Check resolver health and expiry timestamps.','Do not force an outcome without market-data evidence.'],
          'STALE_RESOLUTION_CLAIM':['Inspect resolver worker logs and claim ownership.','Reset a claim only under an approved recovery procedure.'],
        }
        return mapping.get(code, ['Preserve the source database and logs.','Review the entity in Episode Audit.','Document any manual action; this console performs no repair.'])
    def snapshot(self, capture: bool=False) -> dict[str, Any]:
        ledger = self.ledger.capture() if capture else self.ledger.snapshot()
        alerts = self.policy.evaluate(ledger)
        alert_by_key={r['incident_key']:r for r in alerts.get('alerts',[])}
        rows=[]
        for inc in ledger.get('incidents',[]):
            a=alert_by_key.get(inc.get('incident_key'),{})
            rows.append({**inc,'alert_level':a.get('alert_level','NONE'),'alert_reasons':a.get('alert_reasons',[]),'manual_guidance':self.guidance(str(inc.get('code','')))})
        return {'schema':self.SCHEMA_VERSION,'generated_at':datetime.now(timezone.utc).isoformat(),'source_status':ledger.get('source_status'),'incident_count':len(rows),'alert_status':alerts.get('status'),'level_counts':alerts.get('level_counts',{}),'incidents':rows,'recent_snapshots':ledger.get('snapshots',[])[:20],'recent_alert_events':alerts.get('events',[])[:50],'notes':['Read-only operations view.','No automatic remediation or Decision Engine modification.']}
    @staticmethod
    def export_json(payload: dict[str,Any], path: str|Path)->Path:
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8'); return p
    @staticmethod
    def export_html(payload: dict[str,Any], path: str|Path)->Path:
        rows=''.join('<tr>'+''.join(f'<td>{html.escape(str(v))}</td>' for v in [r.get('alert_level'),r.get('severity'),r.get('code'),r.get('entity'),r.get('entity_id'),r.get('state'),'; '.join(r.get('alert_reasons',[]))])+'</tr>' for r in payload.get('incidents',[]))
        body=f'''<!doctype html><meta charset="utf-8"><title>DVS AI Integrity Operations Report</title><h1>DVS AI Integrity Operations Report</h1><p>Generated: {html.escape(str(payload.get('generated_at')))}</p><p>Incidents: {payload.get('incident_count')} · Alert status: {html.escape(str(payload.get('alert_status')))}</p><p><strong>Read-only report. No automatic remediation.</strong></p><table border="1" cellspacing="0" cellpadding="5"><tr><th>Alert</th><th>Severity</th><th>Code</th><th>Entity</th><th>ID</th><th>State</th><th>Reason</th></tr>{rows}</table>'''
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(body,encoding='utf-8'); return p
