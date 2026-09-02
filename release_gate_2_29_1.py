import compileall, subprocess, sys
if not compileall.compile_dir('.', quiet=1):
    raise SystemExit('compile failed')
subprocess.run([sys.executable,'verify_historical_snapshot_runtime_2_29_1.py'],check=True)
subprocess.run([sys.executable,'-m','pytest','-q'],check=True)
print('RELEASE GATE 2.29.1: PASS')
