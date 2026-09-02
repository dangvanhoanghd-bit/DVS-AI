from pathlib import Path
checks={
 'version':'APP_VERSION = "2.29.2"' in Path('dvs_ai/ui/main_window.py').read_text(),
 'module':Path('dvs_ai/services/historical_readiness_trend.py').exists(),
 'runtime':'HistoricalReadinessTrendAudit' in Path('dvs_ai/services/historical_snapshot_runtime.py').read_text(),
 'no_execution':'send_order' not in Path('dvs_ai/services/historical_readiness_trend.py').read_text().lower(),
 'live_locked':'"execution_live_enabled": false' in Path('config.json').read_text().lower(),
}
failed=[k for k,v in checks.items() if not v]
if failed: raise SystemExit('FAILED: '+', '.join(failed))
print('Historical Readiness Trend 2.29.2 verifier: PASS')
