import subprocess, sys
steps=[
 [sys.executable,'verify_production_validation_framework_2_32_5.py'],
 [sys.executable,'-m','pytest','-q'],
]
for step in steps:
    rc=subprocess.call(step)
    if rc: raise SystemExit(rc)
print('RELEASE GATE 2.32.5: PASS')
