from __future__ import annotations
import compileall, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
assert compileall.compile_dir(ROOT/'dvs_ai', quiet=1)
subprocess.run([sys.executable,'verify_gap_backfill_2_25_3.py'],cwd=ROOT,check=True)
subprocess.run([sys.executable,'-m','pytest','-q'],cwd=ROOT,check=True)
print('RELEASE GATE 2.25.3: PASS')
