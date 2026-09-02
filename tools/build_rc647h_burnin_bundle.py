from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import argparse, json
from dvs_ai.governance.burnin_bundle import build_burnin_validation_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Build RC6.4.7H independent burn-in evidence bundle")
    parser.add_argument("--root", default=".", help="DVS AI project root")
    parser.add_argument("--output", default="RC6.4.7H_BURNIN_VALIDATION_BUNDLE", help="Output bundle directory")
    parser.add_argument("--shutdown-marked", action="store_true", help="Classify a malformed tail as interrupted shutdown")
    args = parser.parse_args()
    result = build_burnin_validation_bundle(Path(args.root), Path(args.output), shutdown_marked=args.shutdown_marked)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
