import compileall
import os
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
assert compileall.compile_dir(ROOT/'dvs_ai', quiet=1)
subprocess.run([sys.executable,'verify_adaptive_confidence_2_26_2.py'],cwd=ROOT,check=True)
subprocess.run([sys.executable,'-m','pytest','-q'],cwd=ROOT,check=True,env={**os.environ,'PYTHONPATH':str(ROOT)})
print('RELEASE GATE 2.26.3: PASS')
