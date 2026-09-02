from pathlib import Path

root=Path('.')
service=(root/'dvs_ai/services/operational_validation_service.py').read_text()
ui=(root/'dvs_ai/ui/truth_dashboard.py').read_text()
main=(root/'dvs_ai/ui/main_window.py').read_text()
checks={
    'version':'APP_VERSION = "2.31.0"' in main and '2.31.0-alpha' in (root/'dvs_ai/__init__.py').read_text(),
    'five_engines':all(token in service for token in ('DataCoverageEngine','ConfidenceDistributionEngine','RegimeValidationEngine','OperationalAlertCenter','AIHealthService')),
    'history_append_only':'CREATE TABLE IF NOT EXISTS ai_health_history' in service and 'snapshot_key TEXT NOT NULL UNIQUE' in service,
    'dashboard_integration':all(token in ui for token in ('Operational Validation Center','coverage_table','confidence_table','regime_table','alert_table','OperationalValidationPlatform')),
    'observe_only':all(token not in service for token in ('send_order','TradeIntentBuilder','PositionSizer','ShadowPromotionService','config.json')),
    'live_locked':'execution_live_enabled' not in service,
}
failed=[name for name,ok in checks.items() if not ok]
if failed:
    raise SystemExit('OPERATIONAL VALIDATION VERIFIER FAIL: '+', '.join(failed))
print('OPERATIONAL VALIDATION VERIFIER 2.31.0: PASS')
