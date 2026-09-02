from __future__ import annotations

import argparse
import json
from pathlib import Path

from dvs_ai.services.quantum_data_convergence import EpisodeOutcomeSource, PaperTradeSource, QuantumDataAdapter
from dvs_ai.services.quantum_statistical_burn_in import StatisticalBurnInService


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify QBP-2 statistical burn-in readiness (observe only).")
    parser.add_argument("--db", default="data/dvs_paper_trades.db")
    parser.add_argument("--output")
    args = parser.parse_args()
    db = Path(args.db)
    rows = QuantumDataAdapter(PaperTradeSource(db), EpisodeOutcomeSource(db)).read_terminal()
    payload = StatisticalBurnInService().evaluate(rows).to_dict()
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
