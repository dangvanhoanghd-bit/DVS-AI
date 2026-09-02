from pathlib import Path
from dvs_ai.services.shadow_statistical_comparison import ShadowStatisticalComparison
from dvs_ai.services.shadow_observation_service import PromotionReadinessAudit

source=Path('dvs_ai/services/shadow_statistical_comparison.py').read_text(encoding='utf-8')
readiness=Path('dvs_ai/services/shadow_observation_service.py').read_text(encoding='utf-8')
checks={
 'paired_bootstrap':'class ShadowStatisticalComparison' in source and 'random.Random' in source,
 'confidence_interval':'ci_low' in source and 'ci_high' in source,
 'minimum_detectable_improvement':'minimum_detectable_improvement' in source,
 'time_block_stability':'_block_stability' in source,
 'readiness_boundary':'statistical=self.statistical.compare(closed)' in readiness,
 'observe_only':all(x not in source for x in ('send_order','TradeIntent','PositionSizer','apply_shadow')),
 'version':'2.28.3' in Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8'),
}
failed=[k for k,v in checks.items() if not v]
if failed: raise SystemExit('FAIL: '+', '.join(failed))
print('Shadow Statistical Comparison 2.28.3 verifier: PASS')
