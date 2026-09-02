import compileall, subprocess, sys
if not compileall.compile_dir('dvs_ai',quiet=1): raise SystemExit('compile failed')
subprocess.run([sys.executable,'verify_historical_readiness_trend_2_29_2.py'],check=True)
subprocess.run([sys.executable,'-m','pytest','-q'],check=True)
print('RELEASE GATE 2.29.2: PASS')
