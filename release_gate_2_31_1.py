import subprocess,sys
for cmd in ([sys.executable,'verify_operational_validation_hardening_2_31_1.py'],[sys.executable,'-m','pytest','-q']):
    result=subprocess.run(cmd)
    if result.returncode: raise SystemExit(result.returncode)
print('Release Gate 2.31.1: PASS')
