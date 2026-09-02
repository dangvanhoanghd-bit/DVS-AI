from pathlib import Path
import ast

root=Path(__file__).resolve().parent
contract=(root/'dvs_ai/services/quantum_report_contract.py').read_text(encoding='utf-8')
main=(root/'dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
app=(root/'dvs_ai/app.py').read_text(encoding='utf-8')
shadow=(root/'dvs_ai/services/shadow_observation_service.py').read_text(encoding='utf-8')
assert 'report["base_validation"]' not in main
assert 'build_quantum_report_view(report)' in main
assert 'ShadowObservationStore(paper_db_path)' in app
assert 'LearningService(paper_db_path)' in app
assert 'schema_diagnostics' in shadow and 'idx_shadow_observation_key' in shadow
ast.parse(contract); ast.parse(main); ast.parse(app); ast.parse(shadow)
print('RUNTIME CONTRACT & DB ALIGNMENT VERIFIER 2.32.5-r3: PASS')
