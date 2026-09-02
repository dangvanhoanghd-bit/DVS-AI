from __future__ import annotations

import argparse
from dvs_ai.services.quantum_counterfactual import verify_ablation_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a sealed DVS AI 4.3.0D-2 ablation bundle")
    parser.add_argument("result")
    parser.add_argument("manifest")
    args = parser.parse_args()
    ok, detail = verify_ablation_bundle(args.result, args.manifest)
    print(("VERIFIED" if ok else "INVALID") + ": " + detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
