import compileall, subprocess, sys
if not compileall.compile_dir('.', quiet=1): raise SystemExit('compile failed')
subprocess.run([sys.executable,'verify_shadow_observation_runtime_2_28_1.py'],check=True)
subprocess.run([sys.executable,'-m','pytest','-q'],check=True,env={**__import__('os').environ,'PYTHONPATH':'.'})
print('RELEASE GATE 2.28.2: PASS')
