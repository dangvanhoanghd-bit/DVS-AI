from __future__ import annotations
import argparse, json
from pathlib import Path
from dvs_ai.services.quantum_burn_in_program import QuantumBurnInProgram
from dvs_ai.services.quantum_burn_in_qualification import QBP1ReleaseQualifier


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify QBP-1 operational completion")
    parser.add_argument("--db", default="data/dvs_paper_trades.db")
    parser.add_argument("--ledger", default="data/quantum_burn_in_milestones.jsonl")
    parser.add_argument("--history", default="data/quantum_burn_in_history.jsonl")
    parser.add_argument("--latest", default="data/quantum_burn_in_latest.json")
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args()
    if args.persist:
        QuantumBurnInProgram(args.db, ledger_path=args.ledger, history_path=args.history, latest_snapshot_path=args.latest).snapshot(
            persist_milestones=True, persist_history=True
        )
    result = QBP1ReleaseQualifier(args.db, ledger_path=args.ledger, history_path=args.history).evaluate().to_dict()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"].startswith("QUALIFIED_OBSERVE_ONLY") else 2

if __name__ == "__main__":
    raise SystemExit(main())
