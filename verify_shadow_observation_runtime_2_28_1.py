from pathlib import Path

service=Path('dvs_ai/services/shadow_observation_service.py').read_text(encoding='utf-8')
paper=Path('dvs_ai/services/paper_trade_service.py').read_text(encoding='utf-8')
app=Path('dvs_ai/app.py').read_text(encoding='utf-8')
ui=Path('dvs_ai/ui/truth_dashboard.py').read_text(encoding='utf-8')
checks={
 'runtime_class':'class ShadowObservationRuntime' in service,
 'trade_id_binding':'paper_trade_id' in service and 'close_for_trade' in service,
 'paired_boundary':'main_ok' in paper and 'shadow_ok' in paper and 'record_pair' in paper,
 'outcome_link':'close_trade(trade_id' in paper,
 'shared_runtime':'observation_runtime=shadow_observation_runtime' in app,
 'dashboard_telemetry':'Shadow Observation Runtime' in ui,
 'no_execution':'send_order' not in service and 'TradeIntent' not in service,
 'version':'2.28.2' in Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8'),
}
failed=[k for k,v in checks.items() if not v]
if failed: raise SystemExit('FAIL: '+', '.join(failed))
print('Shadow Observation Runtime 2.28.2 verifier: PASS')
