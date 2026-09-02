from pathlib import Path
checks = {
    'runtime': Path('dvs_ai/services/historical_snapshot_runtime.py').exists(),
    'snapshot_key': 'snapshot_key' in Path('dvs_ai/services/historical_candidate_store.py').read_text(),
    'runtime_wired': 'snapshot_runtime.capture' in Path('dvs_ai/services/shadow_observation_service.py').read_text(),
    'version': 'APP_VERSION = "2.29.1"' in Path('dvs_ai/ui/main_window.py').read_text(),
    'live_disabled': '"execution_live_enabled": false' in Path('config.json').read_text().lower(),
}
failed=[name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit('FAIL: '+', '.join(failed))
print('Historical Snapshot Runtime 2.29.1 verifier: PASS')
