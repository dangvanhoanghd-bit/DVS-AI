import subprocess, sys
steps=[
 [sys.executable,'-m','py_compile','dvs_ai/services/testnet_readiness_service.py'],
 [sys.executable,'verify_testnet_readiness_2_32_0.py'],
 [sys.executable,'-m','pytest','-q'],
]
for step in steps:
    result=subprocess.run(step)
    if result.returncode: raise SystemExit(result.returncode)
print('RELEASE_GATE_2.32.0: PASS')
