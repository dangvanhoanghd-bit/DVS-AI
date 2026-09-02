from pathlib import Path
import compileall, subprocess, sys
ROOT = Path(__file__).resolve().parent
assert compileall.compile_dir(ROOT/'dvs_ai', quiet=1)
subprocess.run([sys.executable, 'verify_evidence_fusion_2_26_0.py'], cwd=ROOT, check=True)
subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=ROOT, check=True)
print('RELEASE GATE 2.26.0: PASS')
