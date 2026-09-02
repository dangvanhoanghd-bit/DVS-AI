import compileall, subprocess, sys, os
assert compileall.compile_dir('.',quiet=1)
subprocess.run([sys.executable,'verify_historical_candidate_platform_2_29_0.py'],check=True)
subprocess.run([sys.executable,'-m','pytest','-q'],check=True,env={**os.environ,'PYTHONPATH':'.'})
print('RELEASE GATE 2.29.0: PASS')
