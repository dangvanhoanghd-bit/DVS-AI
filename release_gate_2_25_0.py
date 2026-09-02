from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
commands = [
    [sys.executable, "-m", "compileall", "-q", "dvs_ai", "tests"],
    [sys.executable, "verify_position_building_2_25_0.py"],
    [sys.executable, "-m", "pytest", "-q"],
]
for command in commands:
    print("$", " ".join(command), flush=True)
    result = subprocess.run(command, cwd=root)
    if result.returncode:
        raise SystemExit(result.returncode)
print("RELEASE GATE 2.25.0: PASS")
