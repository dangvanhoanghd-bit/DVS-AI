import subprocess, sys
steps = [
    [sys.executable, '-m', 'compileall', '-q', 'dvs_ai'],
    [sys.executable, 'verify_quantum_lab_hardening_2_26_7.py'],
    [sys.executable, '-m', 'pytest', '-q'],
]
for step in steps:
    subprocess.run(step, check=True)
print('RELEASE GATE 2.26.7: PASS')
