from __future__ import annotations

import argparse
import json
from pathlib import Path

from dvs_ai.services.quantum_data_convergence.adapter import QuantumDataAdapter
from dvs_ai.services.quantum_data_convergence.sources import EpisodeOutcomeSource, PaperTradeSource
from dvs_ai.services.quantum_statistical_validation import QuantumGovernanceHandoverService, QuantumStatisticalValidationService


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify QBP-3 statistical validation and QBP-4 governance review")
    parser.add_argument("--db", default="data/dvs_paper_trades.db")
    parser.add_argument("--p-values-json", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    p_values = {}
    if args.p_values_json:
        p_values = json.loads(Path(args.p_values_json).read_text(encoding="utf-8"))
    rows = QuantumDataAdapter(PaperTradeSource(args.db), EpisodeOutcomeSource(args.db)).read_terminal()
    qbp3 = QuantumStatisticalValidationService().evaluate(rows, candidate_p_values=p_values)
    qbp4 = QuantumGovernanceHandoverService().evaluate(qbp3)
    payload = {"qbp3": qbp3.to_dict(), "qbp4": qbp4.to_dict()}
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
