import subprocess, sys
from pathlib import Path
root=Path(__file__).resolve().parent
subprocess.run([sys.executable, 'verify_operational_ux_2_32_5_r5.py'], cwd=root, check=True)
subprocess.run([sys.executable, '-m', 'pytest', '-q', 'tests/test_v2325_r5_operational_ux.py'], cwd=root, check=True)
print('RELEASE GATE 2.32.5-r5: PASS')
