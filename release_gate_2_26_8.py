import subprocess, sys
for step in ([sys.executable,'-m','compileall','-q','dvs_ai'],[sys.executable,'verify_quantum_shadow_truth_trends_2_26_8.py'],[sys.executable,'-m','pytest','-q']):
    subprocess.run(step,check=True)
print('RELEASE GATE 2.26.8: PASS')
