import subprocess, sys
commands=[
    [sys.executable,'verify_operational_validation_2_31_0.py'],
    [sys.executable,'-m','pytest','-q','tests/test_v2310_operational_validation_platform.py'],
    [sys.executable,'-m','pytest','-q'],
]
for command in commands:
    result=subprocess.run(command)
    if result.returncode:
        raise SystemExit(result.returncode)
print('RELEASE GATE 2.31.0: PASS')
