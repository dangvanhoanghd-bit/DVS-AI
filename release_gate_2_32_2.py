import subprocess, sys
steps=[
 [sys.executable,'verify_evidence_analysis_2_32_2.py'],
 [sys.executable,'-m','pytest','-q','tests/test_v2322_evidence_analysis_engine.py'],
 [sys.executable,'-m','pytest','-q'],
]
for step in steps:
    result=subprocess.run(step)
    if result.returncode: raise SystemExit(result.returncode)
print('RELEASE GATE 2.32.2: PASS')
