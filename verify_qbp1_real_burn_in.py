from __future__ import annotations

import argparse
import json
from pathlib import Path

from dvs_ai.services.quantum_burn_in_program import QuantumBurnInProgram


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify QBP-1 real burn-in infrastructure")
    parser.add_argument("--db", default="data/dvs_paper_trades.db")
    parser.add_argument("--ledger", default="data/quantum_burn_in_milestones.jsonl")
    parser.add_argument("--persist-milestones", action="store_true")
    args = parser.parse_args()
    program = QuantumBurnInProgram(Path(args.db), ledger_path=Path(args.ledger))
    report = program.snapshot(persist_milestones=args.persist_milestones).to_dict()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["authority_granted"] is False and report["production_or_execution_authority"] is False else 2


if __name__ == "__main__":
    raise SystemExit(main())
