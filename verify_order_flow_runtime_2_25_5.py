from pathlib import Path

ROOT = Path(__file__).resolve().parent
runtime = (ROOT/'dvs_ai/services/order_flow_runtime.py').read_text(encoding='utf-8')
app = (ROOT/'dvs_ai/app.py').read_text(encoding='utf-8')
ui = (ROOT/'dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
scanner = (ROOT/'dvs_ai/services/scanner.py').read_text(encoding='utf-8')

assert 'class OrderFlowRuntime' in runtime
assert 'ControlledAggTradeBackfiller' in runtime
assert 'ResilientOrderFlowCollector' in runtime
assert all(token not in runtime for token in ('TradeIntent', 'PositionSizer', 'send_order'))
assert 'order_flow_store=order_flow_runtime.store' in app
assert 'collector_diagnostics_provider=order_flow_runtime.diagnostics' in app
assert 'microstructure_service=microstructure' in app
assert 'finally:' in app and 'order_flow_runtime.close()' in app
assert 'order_flow_runtime=None' in ui
assert 'self._refresh_order_flow_status()' in ui
assert 'self.order_flow_runtime.close(timeout=5.0)' in ui
assert 'microstructure_service or MicrostructureService(provider)' in scanner
print('ORDER FLOW RUNTIME VERIFY 2.25.5: PASS')
