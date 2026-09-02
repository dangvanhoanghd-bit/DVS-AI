import compileall
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
assert compileall.compile_dir(ROOT/'dvs_ai', quiet=1)
subprocess.run([sys.executable, 'verify_probability_calibration_2_26_1.py'], cwd=ROOT, check=True)
subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=ROOT, check=True, env={**__import__('os').environ, 'PYTHONPATH': str(ROOT)})
print('RELEASE GATE 2.26.1: PASS')
