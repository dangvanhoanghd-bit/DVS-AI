import compileall, subprocess, sys
if not compileall.compile_dir('.', quiet=1): raise SystemExit('compile failed')
subprocess.run([sys.executable,'verify_evidence_validation_2_28_0.py'],check=True)
subprocess.run([sys.executable,'-m','pytest','-q'],check=True)
print('RELEASE GATE 2.28.0: PASS')
