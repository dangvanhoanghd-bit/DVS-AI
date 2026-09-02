import compileall, subprocess, sys
assert compileall.compile_dir('.', quiet=1)
subprocess.run([sys.executable,'verify_shadow_promotion_2_27_0.py'],check=True)
subprocess.run([sys.executable,'-m','pytest','-q'],check=True)
print('RELEASE GATE 2.27.0: PASS')
