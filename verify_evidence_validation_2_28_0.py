from pathlib import Path

checks = {
    'comparison_engine': Path('dvs_ai/services/candidate_evidence_service.py').exists(),
    'observation_store': Path('dvs_ai/services/shadow_observation_service.py').exists(),
    'dashboard_panel': 'Candidate Evidence & Promotion Timeline' in Path('dvs_ai/ui/truth_dashboard.py').read_text(encoding='utf-8'),
    'main_immutable': 'send_order' not in Path('dvs_ai/services/shadow_observation_service.py').read_text(encoding='utf-8'),
    'version': '2.28.0' in Path('dvs_ai/ui/main_window.py').read_text(encoding='utf-8'),
}
failed=[k for k,v in checks.items() if not v]
if failed: raise SystemExit('FAIL: '+', '.join(failed))
print('Evidence Validation 2.28.0 verifier: PASS')
