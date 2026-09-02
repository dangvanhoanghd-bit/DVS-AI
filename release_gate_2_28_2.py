import compileall, subprocess, sys
assert compileall.compile_dir('.',quiet=1)
subprocess.run([sys.executable,'verify_observation_quality_2_28_2.py'],check=True)
subprocess.run([sys.executable,'-m','pytest','-q'],check=True,env={**__import__('os').environ,'PYTHONPATH':'.'})
print('RELEASE GATE 2.28.2: PASS')
