from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
subprocess.run([sys.executable, '-m', 'compileall', '-q', 'dvs_ai', 'tests'], cwd=ROOT, check=True)
subprocess.run([sys.executable, 'verify_order_flow_quality_2_25_4.py'], cwd=ROOT, check=True)
subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=ROOT, check=True)
print('RELEASE GATE 2.25.4: PASS')
