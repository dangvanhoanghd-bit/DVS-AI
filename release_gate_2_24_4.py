from __future__ import annotations
import compileall, json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def run(cmd):
    print('>', ' '.join(cmd), flush=True)
    return subprocess.run(cmd,cwd=ROOT,check=False).returncode

print('[1/4] Compile repository')
if not compileall.compile_dir(ROOT,quiet=1): raise SystemExit(1)
print('[2/4] Truth verifier')
if run([sys.executable,'verify_release_2_24_4.py']): raise SystemExit(2)
print('[3/4] Full pytest')
if run([sys.executable,'-m','pytest','-q']): raise SystemExit(3)
print('[4/4] Safety invariant')
cfg=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
assert cfg['execution_mode']=='PAPER' and cfg['execution_live_enabled'] is False
print('RELEASE GATE 2.24.4: PASS')
