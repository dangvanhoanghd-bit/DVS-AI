import subprocess, sys
commands = [
    [sys.executable, '-m', 'compileall', '-q', 'dvs_ai'],
    [sys.executable, 'verify_evidence_fusion_v3_2_26_6.py'],
    [sys.executable, '-m', 'pytest', '-q'],
]
for command in commands:
    result = subprocess.run(command)
    if result.returncode:
        raise SystemExit(result.returncode)
print('RELEASE GATE 2.26.6: PASS')
