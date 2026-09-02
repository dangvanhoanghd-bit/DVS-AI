from pathlib import Path
from dvs_ai.services.shadow_observation_service import ObservationQualityAudit, PromotionReadinessAudit
source=Path('dvs_ai/services/shadow_observation_service.py').read_text(encoding='utf-8')
checks={
 'quality_gate':'class ObservationQualityAudit' in source,
 'eligible_rows':'eligible_rows' in source,
 'readiness_boundary':'quality_result' in source,
 'no_execution':all(x not in source for x in ('send_order','TradeIntent','PositionSizer')),
 'version':'2.28.2' in Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8'),
}
failed=[k for k,v in checks.items() if not v]
if failed: raise SystemExit('FAIL: '+', '.join(failed))
print('Observation Quality & Coverage 2.28.2 verifier: PASS')
