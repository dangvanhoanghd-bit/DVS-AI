from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from dvs_ai.services.quantum_burn_in import QuantumBurnInService
from dvs_ai.services.quantum_data_convergence import DataEquivalenceVerifier


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify QBP-0D/QBP-0E release candidate")
    parser.add_argument("--db", default="data/dvs_paper_trades.db")
    parser.add_argument("--output", default="artifacts/qbp0_release_candidate_report.json")
    args = parser.parse_args()

    equivalence = DataEquivalenceVerifier(args.db).verify()
    burn_in = QuantumBurnInService(args.db).snapshot()
    report = {
        "schema_version": "dvs-qbp0-release-candidate-v1",
        "release": "4.3.0E-3-QBP-0-RC1",
        "data_equivalence": equivalence.to_dict(),
        "burn_in": burn_in.to_dict(),
        "release_candidate_ready_for_audit": equivalence.equivalent,
        "production_or_execution_authority": False,
        "paper_authority_handover_granted": False,
    }
    report["self_sha256"] = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if equivalence.equivalent else 2


if __name__ == "__main__":
    raise SystemExit(main())
