from __future__ import annotations

import compileall
import subprocess
import sys
from pathlib import Path

root=Path(__file__).resolve().parent
assert compileall.compile_dir(root/'dvs_ai', quiet=1)
subprocess.run([sys.executable, str(root/'verify_data_pipeline_integrity_2_32_5_r2.py')], cwd=root, check=True)
subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=root, check=True)
print('RELEASE GATE 2.32.5-r2: PASS')
