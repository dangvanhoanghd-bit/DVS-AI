from __future__ import annotations
import subprocess, sys

commands = [
    [sys.executable, '-m', 'compileall', '-q', 'dvs_ai'],
    [sys.executable, 'verify_truth_dashboard_2_26_5.py'],
    [sys.executable, '-m', 'pytest', '-q'],
]
for command in commands:
    print('>', ' '.join(command), flush=True)
    result = subprocess.run(command)
    if result.returncode:
        raise SystemExit(result.returncode)
print('RELEASE GATE 2.26.5: PASS')
