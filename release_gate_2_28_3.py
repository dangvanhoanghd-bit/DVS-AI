import compileall, subprocess, sys, os
assert compileall.compile_dir('.',quiet=1)
subprocess.run([sys.executable,'verify_shadow_statistical_comparison_2_28_3.py'],check=True)
subprocess.run([sys.executable,'-m','pytest','-q'],check=True,env={**os.environ,'PYTHONPATH':'.'})
print('RELEASE GATE 2.28.3: PASS')
