from __future__ import annotations
import subprocess
import sys

commands = [
    [sys.executable, '-m', 'py_compile', 'dvs_ai/ui/truth_dashboard.py', 'dvs_ai/ui/main_window.py'],
    [sys.executable, 'verify_truth_dashboard_v3_2_30_0.py'],
    [sys.executable, '-m', 'pytest', '-q'],
]
for command in commands:
    print('RUN:', ' '.join(command), flush=True)
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)
print('RELEASE GATE 2.30.0: PASS')
