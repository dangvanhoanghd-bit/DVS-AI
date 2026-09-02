from pathlib import Path
checks={
 'lifecycle_store': Path('dvs_ai/services/candidate_lifecycle_store.py').exists(),
 'performance_store': Path('dvs_ai/services/historical_candidate_store.py').exists(),
 'append_only': 'INSERT INTO candidate_lifecycle_events' in Path('dvs_ai/services/candidate_lifecycle_store.py').read_text(),
 'dashboard': 'Historical Candidate Performance' in Path('dvs_ai/ui/truth_dashboard.py').read_text(),
 'observe_only': all(x not in Path('dvs_ai/services/candidate_lifecycle_store.py').read_text()+Path('dvs_ai/services/historical_candidate_store.py').read_text() for x in ('send_order','TradeIntent','PositionSizer')),
 'version': 'APP_VERSION = "2.29.0"' in Path('dvs_ai/ui/main_window.py').read_text(),
}
failed=[k for k,v in checks.items() if not v]
if failed: raise SystemExit('FAIL: '+', '.join(failed))
print('Historical Candidate Platform 2.29.0 verifier: PASS')
