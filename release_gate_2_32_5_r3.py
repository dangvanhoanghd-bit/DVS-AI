import subprocess,sys
steps=[
 [sys.executable,'verify_runtime_contract_db_alignment_2_32_5_r3.py'],
 [sys.executable,'-m','pytest','-q','tests/test_v2325_r3_runtime_contract_and_db_alignment.py'],
]
for cmd in steps:
 r=subprocess.run(cmd)
 if r.returncode: raise SystemExit(r.returncode)
print('RELEASE GATE 2.32.5-r3: PASS')
