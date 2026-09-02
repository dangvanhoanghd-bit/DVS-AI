from dvs_ai.services.integrity_operations_console import IntegrityOperationsConsoleService

def test_guidance_is_deterministic():
 a=IntegrityOperationsConsoleService.guidance('SEQUENCE_GAP'); b=IntegrityOperationsConsoleService.guidance('SEQUENCE_GAP'); assert a==b and 'renumber' in ' '.join(a).lower()

def test_export_report(tmp_path):
 payload={'generated_at':'x','incident_count':1,'alert_status':'WATCH','incidents':[{'alert_level':'WATCH','severity':'WARNING','code':'X','entity':'episode','entity_id':'1','state':'OPEN','alert_reasons':['reason']} ]}
 jp=IntegrityOperationsConsoleService.export_json(payload,tmp_path/'r.json'); hp=IntegrityOperationsConsoleService.export_html(payload,tmp_path/'r.html')
 assert 'WATCH' in jp.read_text() and 'Read-only report' in hp.read_text()
