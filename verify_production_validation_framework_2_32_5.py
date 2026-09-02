from pathlib import Path
from dvs_ai.services.evidence_analysis.protocol_enforcement import EvidenceProtocolEnforcer
base=Path('dvs_ai/services/evidence_analysis')
for name in ('executive_report.py','protocol_enforcement.py'):
    assert (base/name).exists(), name
report=EvidenceProtocolEnforcer.audit_source(base)
assert report.state=='PASS', report.issues
text=(base/'executive_report.py').read_text(encoding='utf-8').lower()
assert 'artifact_hash' in text and 'append-only' in text
print('PRODUCTION VALIDATION FRAMEWORK VERIFIER 2.32.5: PASS')
