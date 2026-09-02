from __future__ import annotations

import argparse

from dvs_ai.services.quantum_governance import verify_audit_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a DVS AI 4.3.0E-3 Quantum audit bundle")
    parser.add_argument("bundle", help="Path to the extracted audit bundle directory")
    args = parser.parse_args()
    result = verify_audit_bundle(args.bundle)
    print("VALID" if result.valid else "INVALID")
    for violation in result.violations:
        print(violation)
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
