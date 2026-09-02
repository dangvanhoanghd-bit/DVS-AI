from pathlib import Path
import subprocess, sys
ROOT=Path(__file__).resolve().parent
commands=[
    [sys.executable,'-m','compileall','-q','dvs_ai'],
    [sys.executable,'verify_composite_exhaustion_2_32_5_r6.py'],
    [sys.executable,'-m','pytest','-q'],
]
for cmd in commands:
    result=subprocess.run(cmd,cwd=ROOT)
    if result.returncode:
        raise SystemExit(result.returncode)
print('Release Gate 2.32.5-r6: PASS')
