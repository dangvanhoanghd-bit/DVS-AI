import subprocess, sys
steps=[
 [sys.executable,'verify_confidence_gap_framework_2_32_3.py'],
 [sys.executable,'-m','pytest','-q','tests/test_v2323_confidence_gap_framework.py'],
 [sys.executable,'-m','pytest','-q'],
]
for command in steps:
    result=subprocess.run(command)
    if result.returncode:
        raise SystemExit(result.returncode)
print('RELEASE GATE 2.32.5: PASS')
