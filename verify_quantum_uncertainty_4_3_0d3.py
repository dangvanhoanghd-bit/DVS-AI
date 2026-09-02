from __future__ import annotations

import argparse
from dvs_ai.services.quantum_counterfactual import verify_uncertainty_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a sealed DVS AI Quantum uncertainty bundle.")
    parser.add_argument("result")
    parser.add_argument("manifest")
    args = parser.parse_args()
    ok, detail = verify_uncertainty_bundle(args.result, args.manifest)
    print(("VERIFIED" if ok else "BLOCKED") + f": {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
