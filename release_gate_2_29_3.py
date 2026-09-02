from __future__ import annotations

import compileall
import subprocess
import sys


def run(*args: str) -> None:
    subprocess.run([sys.executable, *args], check=True)


def main() -> int:
    if not compileall.compile_dir("dvs_ai", quiet=1):
        raise SystemExit("Compile repository: FAIL")
    print("Compile repository: PASS")
    run("verify_historical_evidence_platform_2_29_3.py")
    run("-m", "pytest", "-q")
    print("RELEASE GATE 2.29.3: PASS")
    print("MAIN immutable; LIVE execution disabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
