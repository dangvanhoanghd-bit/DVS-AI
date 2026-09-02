from __future__ import annotations
import argparse
import json
from pathlib import Path
from dvs_ai.services.quantum_release_qualification import QuantumReleaseQualifier


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify DVS AI Quantum QI-3 release readiness")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--output", default="data/quantum_release_qualification.json")
    args = parser.parse_args()
    qualifier = QuantumReleaseQualifier(Path(args.project_root))
    report = qualifier.run()
    output = qualifier.write_report(Path(args.project_root) / args.output)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    print(f"Report: {output}")
    return 0 if report.qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())
