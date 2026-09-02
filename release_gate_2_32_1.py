import subprocess,sys
steps=[
 [sys.executable,'-m','py_compile','dvs_ai/services/evidence_analysis/observable_models.py','dvs_ai/services/evidence_analysis/observable_thresholds.py','dvs_ai/services/evidence_analysis/threshold_governance.py','dvs_ai/services/evidence_analysis/observable_repository.py','dvs_ai/services/evidence_analysis/observable_universe.py','dvs_ai/services/evidence_analysis/protocol_gate.py'],
 [sys.executable,'verify_observable_universe_2_32_1.py'],
 [sys.executable,'-m','pytest','-q','tests/test_v2321_observable_universe.py'],
 [sys.executable,'-m','pytest','-q'],
]
for step in steps:
    print('RUN', ' '.join(step)); subprocess.run(step,check=True)
print('RELEASE GATE 2.32.1: PASS')
