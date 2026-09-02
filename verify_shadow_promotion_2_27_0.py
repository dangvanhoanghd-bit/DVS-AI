from pathlib import Path

ROOT=Path(__file__).parent
checks={
 'backtest service': ROOT/'dvs_ai/services/quantum_candidate_backtest.py',
 'promotion service': ROOT/'dvs_ai/services/shadow_promotion_service.py',
 'workflow tests': ROOT/'tests/test_v2270_shadow_promotion_workflow.py',
}
for name,path in checks.items():
    assert path.exists(), f'missing {name}'
text=(ROOT/'dvs_ai/services/shadow_promotion_service.py').read_text()
assert 'ALLOWED_KEYS' in text and 'APPLY TO SHADOW' in text
assert 'main_unchanged' in text and 'backup_path' in text
ui=(ROOT/'dvs_ai/ui/main_window.py').read_text()
assert 'Apply to SHADOW' in ui and 'Review 1/2' in ui and 'Confirm 2/2' in ui
assert 'APP_VERSION = "2.27.0"' in ui
print('VERIFY 2.27.0: PASS')
