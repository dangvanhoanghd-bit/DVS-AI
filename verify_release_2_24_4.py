from pathlib import Path
import json
ROOT=Path(__file__).resolve().parent
main=(ROOT/'dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
manifest=json.loads((ROOT/'RELEASE_TRUTH_MANIFEST.json').read_text(encoding='utf-8'))
config=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
checks={
 'version': 'APP_VERSION = "2.24.4"' in main and '2.24.4-alpha' in (ROOT/'dvs_ai/__init__.py').read_text(encoding='utf-8'),
 'edition': 'APP_EDITION = "Release Truth Audit"' in main,
 'manifest': manifest.get('release')=='2.24.4-alpha' and len(manifest.get('claims',[]))>=5,
 'no_false_virtualization_claim': any(c.get('id')=='virtual_table' and c.get('status')=='not_claimed' for c in manifest['claims']),
 'cell_diff': (ROOT/'dvs_ai/ui/frame_paint_scheduler.py').exists() and '_table_diff_metrics' in main,
 'overlay': (ROOT/'dvs_ai/ui/performance_overlay.py').exists(),
 'paper_safety': config.get('execution_mode')=='PAPER' and config.get('execution_live_enabled') is False,
}
failed=[k for k,v in checks.items() if not v]
for k,v in checks.items(): print(('PASS' if v else 'FAIL'),k)
if failed: raise SystemExit('Release verifier failed: '+', '.join(failed))
print('DVS AI Alpha 2.24.4 truth verifier: PASS')
