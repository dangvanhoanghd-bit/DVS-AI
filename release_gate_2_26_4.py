import compileall, subprocess, sys
assert compileall.compile_dir('.', quiet=1)
subprocess.run([sys.executable,'verify_evidence_reliability_2_26_4.py'],check=True)
subprocess.run([sys.executable,'-m','pytest','-q'],check=True)
print('RELEASE GATE 2.26.4: PASS')
