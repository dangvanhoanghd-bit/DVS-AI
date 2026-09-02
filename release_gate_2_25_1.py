from __future__ import annotations

import subprocess
import sys


def run(*args: str) -> None:
    subprocess.run([sys.executable, *args], check=True)


def main() -> int:
    run("-m", "compileall", "-q", "dvs_ai", "tests")
    run("verify_order_flow_2_25_1.py")
    run("-m", "pytest", "-q")
    print("RELEASE GATE 2.25.1: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
